"""Native nonresident $ATTRIBUTE_LIST values must come from the NTFS image."""

import os
from pathlib import Path
import json
import re
import struct
import tarfile
from contextlib import contextmanager

import pytsk3
import pytest

from ntfsdump.errors import NtfsDumpError
from ntfsfind.core import find_records, ntfsfind


def _decode_fixups(record):
    offset, count = struct.unpack_from("<HH", record, 4)
    marker = record[offset : offset + 2]
    for sector in range(1, count):
        end = sector * 512 - 2
        assert record[end : end + 2] == marker
        record[end : end + 2] = record[offset + sector * 2 : offset + sector * 2 + 2]
    return offset, count, marker


def _encode_fixups(record, offset, count, marker):
    for sector in range(1, count):
        end = sector * 512 - 2
        record[offset + sector * 2 : offset + sector * 2 + 2] = record[end : end + 2]
        record[end : end + 2] = marker


def _resident(type_code, attr_id, name, value):
    encoded = name.encode("utf-16le")
    value_offset = (24 + len(encoded) + 7) // 8 * 8
    size = (value_offset + len(value) + 7) // 8 * 8
    result = bytearray(size)
    struct.pack_into(
        "<IIBBHHH", result, 0, type_code, size, 0, len(name),
        24 if encoded else 0, 0, attr_id,
    )
    struct.pack_into("<IHBB", result, 16, len(value), value_offset, 0, 0)
    result[24 : 24 + len(encoded)] = encoded
    result[value_offset : value_offset + len(value)] = value
    return bytes(result)


def _list_entry(type_code, name, record_id, sequence, attr_id):
    encoded = name.encode("utf-16le")
    size = (26 + len(encoded) + 7) // 8 * 8
    result = bytearray(size)
    struct.pack_into(
        "<IHBBQQH", result, 0, type_code, size, len(name),
        26 if encoded else 0, 0, record_id | sequence << 48, attr_id,
    )
    result[26 : 26 + len(encoded)] = encoded
    return bytes(result)


def _extension_fixture_mft(mft):
    """Return MFT bytes with a base record, alias, ADS and resident list."""
    record = bytearray(mft[52 * 1024 : 53 * 1024])
    usa_offset, usa_count, marker = _decode_fixups(record)
    cursor = struct.unpack_from("<H", record, 20)[0]
    attributes = []
    while struct.unpack_from("<I", record, cursor)[0] != 0xFFFFFFFF:
        size = struct.unpack_from("<I", record, cursor + 4)[0]
        attributes.append(bytes(record[cursor : cursor + size]))
        cursor += size

    def get_attr_id(attribute):
        return struct.unpack_from("<H", attribute, 14)[0]

    # The original FILE_NAME and DATA attributes remain on record 52.
    entries = [
        _list_entry(struct.unpack_from("<I", attr)[0], "", 52, 1, get_attr_id(attr))
        for attr in attributes
    ]
    alias = "extension_alias.txt"
    alias_bytes = alias.encode("utf-16le")
    filename_value = bytearray(66 + len(alias_bytes))
    struct.pack_into("<Q", filename_value, 0, 64 | 1 << 48)
    filename_value[64] = len(alias)
    filename_value[65] = 1
    filename_value[66:] = alias_bytes
    extension_attrs = [
        _resident(48, 6, "", filename_value),
        _resident(128, 5, "extension", b"EXTENSION STREAM"),
    ]
    entries.extend(
        [
            _list_entry(48, "", 100, 1, 6),
            _list_entry(128, "extension", 100, 1, 5),
        ]
    )
    # NTFS orders list entries by type, name and lowest VCN.
    entry_tuples = []
    for entry in entries:
        type_code, _, name_len, name_off = struct.unpack_from("<IHBB", entry)
        name = entry[name_off : name_off + name_len * 2].decode("utf-16le") if name_len else ""
        lowest_vcn = struct.unpack_from("<Q", entry, 8)[0]
        entry_tuples.append(((type_code, name.casefold(), lowest_vcn), entry))
    list_value = b"".join(entry for _, entry in sorted(entry_tuples, key=lambda item: item[0]))

    # Remove a pre-existing list, if present, then install a nonresident list.
    attributes = [a for a in attributes if struct.unpack_from("<I", a)[0] != 32]
    # This test image has a free slot after the source attributes, so keep the
    # base record's attributes intact and append type 32 ahead of FILE_NAME.
    attr_len = 72
    nonresident = bytearray(attr_len)
    struct.pack_into("<IIBBHHH", nonresident, 0, 32, attr_len, 1, 0, 0, 0, 7)
    struct.pack_into("<QQHHI", nonresident, 16, 0, 0, 64, 0, 0)
    struct.pack_into("<QQQ", nonresident, 40, 4096, len(list_value), len(list_value))
    # The one-cluster runlist is filled in after the free cluster is selected.
    return attributes, extension_attrs, nonresident, list_value, record, (usa_offset, usa_count, marker)


def _single_cluster_runlist(cluster):
    # Header 0x11 means one-byte run length and four-byte signed LCN delta.
    return bytes((0x41, 1)) + struct.pack("<i", cluster) + b"\0"


@contextmanager
def _temporary_image_bytes(path, offset, value):
    with path.open("r+b") as image:
        image.seek(offset)
        original = image.read(len(value))
        image.seek(offset)
        image.write(value)
        image.flush()
    try:
        yield
    finally:
        with path.open("r+b") as image:
            image.seek(offset)
            image.write(original)


def _write_record(
    record, attributes, usa, base_reference=0, entry_id=52, hard_link_count=2,
    next_attribute_id=8,
):
    usa_offset, usa_count, marker = usa
    struct.pack_into("<Q", record, 32, base_reference)
    struct.pack_into("<I", record, 44, entry_id)
    struct.pack_into("<H", record, 18, hard_link_count)
    struct.pack_into("<H", record, 22, 1)
    cursor = struct.unpack_from("<H", record, 20)[0]
    for attribute in attributes:
        record[cursor : cursor + len(attribute)] = attribute
        cursor += len(attribute)
    struct.pack_into("<II", record, cursor, 0xFFFFFFFF, 0)
    struct.pack_into("<I", record, 24, cursor + 8)
    struct.pack_into("<H", record, 40, next_attribute_id)
    _encode_fixups(record, usa_offset, usa_count, marker)
    return bytes(record)


@pytest.fixture(scope="module")
def nonresident_attribute_list_image(ntfs_sample, tmp_path_factory):
    """Make an isolated sparse image copy and put the list in a free cluster."""
    directory = tmp_path_factory.mktemp("nonresident-attribute-list")
    destination = directory / "ntfs.raw64GiBsmallactual"
    archive = Path(
        os.environ.get(
            "NTFS_SAMPLE_ARCHIVE", str(Path(__file__).parent / "cache" / "ntfs.tgs")
        )
    )
    with tarfile.open(archive, "r:gz") as compressed:
        member = compressed.getmember("ntfs.raw")
        assert member.isfile()
        compressed.extract(member, directory, filter="data")
    (directory / "ntfs.raw").rename(destination)

    image = pytsk3.Img_Info(str(destination))
    try:
        volume_table = pytsk3.Volume_Info(image)
        partition = next(part for part in volume_table if b"NTFS" in part.desc)
        partition_offset = partition.start * volume_table.info.block_size
        filesystem = pytsk3.FS_Info(image, partition_offset)
        cluster_size = filesystem.info.block_size
        mft_file = filesystem.open("/$MFT")
        mft = mft_file.read_random(0, mft_file.info.meta.size)
        base_attrs, extension_attrs, list_attr, list_value, template, usa = _extension_fixture_mft(mft)
        bitmap_file = filesystem.open("/$Bitmap")
        bitmap = bitmap_file.read_random(0, bitmap_file.info.meta.size)
        mft_bitmap_attribute = next(
            attr for attr in mft_file if attr.info.type == 176
        )
        mft_bitmap = mft_file.read_random(
            0, mft_bitmap_attribute.info.size,
            mft_bitmap_attribute.info.type, mft_bitmap_attribute.info.id,
        )
        assert not mft_bitmap[100 // 8] & (1 << (100 % 8))
        # Pick an actually free, in-volume cluster, excluding metadata cluster 0.
        cluster = next(
            n for n in range(1, min(len(bitmap) * 8, filesystem.info.block_count))
            if not bitmap[n // 8] & (1 << (n % 8))
        )
        bitmap_runs = [run for attr in bitmap_file for run in attr if run.addr]
        list_run = _single_cluster_runlist(cluster)
        struct.pack_into("<I", list_attr, 4, 64 + len(list_run))
        list_attr[64 : 64 + len(list_run)] = list_run
        list_attr.extend(bytes((-(len(list_attr))) % 8))
        struct.pack_into("<I", list_attr, 4, len(list_attr))

        base_record = bytearray(mft[52 * 1024 : 53 * 1024])
        base_usa = _decode_fixups(base_record)
        base_order = sorted(
            base_attrs + [bytes(list_attr)],
            key=lambda attr: (
                struct.unpack_from("<I", attr)[0],
                attr[9],
                attr[10],
                attr[24 : 24 + attr[9] * 2],
            ),
        )
        base_record = bytearray(_write_record(base_record, base_order, base_usa))
        extension = bytearray(1024)
        extension[:len(template[:24])] = template[:24]
        extension[4:8] = template[4:8]
        # Preserve the valid USA template and identify this as record 100.
        ext_template = bytearray(mft[52 * 1024 : 53 * 1024])
        ext_usa = _decode_fixups(ext_template)
        extension = bytearray(ext_template)
        extension_attrs = sorted(
            extension_attrs,
            key=lambda attr: (struct.unpack_from("<I", attr)[0], attr[9], attr[10]),
        )
        extension = bytearray(
            _write_record(
                extension, extension_attrs, ext_usa, 52 | 1 << 48, 100,
                hard_link_count=0, next_attribute_id=7,
            )
        )

        # Persist both records into the actual $MFT run, and allocate the list
        # cluster in the real on-disk $Bitmap.
        mft_runs = [run for attr in mft_file for run in attr if run.addr]
        mft_start = mft_runs[0].addr * cluster_size
        mft_bitmap_runs = [
            run for run in mft_bitmap_attribute if run.addr
        ]
        with destination.open("r+b") as output:
            output.seek(partition_offset + mft_start + 52 * 1024)
            output.write(base_record)
            output.seek(partition_offset + mft_start + 100 * 1024)
            output.write(extension)
            bitmap_run = bitmap_runs[0]
            bitmap_offset = partition_offset + bitmap_run.addr * cluster_size + cluster // 8
            output.seek(bitmap_offset)
            output.write(bytes((bitmap[cluster // 8] | (1 << (cluster % 8)),)))
            mft_bitmap_run = mft_bitmap_runs[0]
            output.seek(
                partition_offset + mft_bitmap_run.addr * cluster_size + 100 // 8
            )
            output.write(bytes((mft_bitmap[100 // 8] | (1 << (100 % 8)),)))
            output.seek(partition_offset + cluster * cluster_size)
            output.write(list_value)
    finally:
        image.close()
    return destination, list_value, {
        "list_offset": partition_offset + cluster * cluster_size,
        "base_record_offset": partition_offset + mft_start + 52 * 1024,
        "extension_record_offset": partition_offset + mft_start + 100 * 1024,
    }


def test_pytsk_reads_nonresident_attribute_list_from_its_run(
    nonresident_attribute_list_image,
):
    image_path, expected, _ = nonresident_attribute_list_image
    image = pytsk3.Img_Info(str(image_path))
    try:
        volume_table = pytsk3.Volume_Info(image)
        partition = next(part for part in volume_table if b"NTFS" in part.desc)
        filesystem = pytsk3.FS_Info(image, partition.start * volume_table.info.block_size)
        extension = filesystem.open_meta(52)
        candidates = [attr for attr in extension if attr.info.type == 32]
        assert len(candidates) == 1
        actual = extension.read_random(
            0, candidates[0].info.size, candidates[0].info.type, candidates[0].info.id
        )
        assert actual == expected
        assert filesystem.open_meta(100).info.meta.addr == 100
        mft_file = filesystem.open("/$MFT")
        bitmap_attribute = next(attr for attr in mft_file if attr.info.type == 176)
        mft_bitmap = mft_file.read_random(
            0, bitmap_attribute.info.size, bitmap_attribute.info.type,
            bitmap_attribute.info.id,
        )
        assert mft_bitmap[100 // 8] & (1 << (100 % 8))
    finally:
        image.close()


def test_image_search_joins_nonresident_extension_stream_and_alias(
    nonresident_attribute_list_image,
):
    image_path, _, _ = nonresident_attribute_list_image
    result = ntfsfind(image_path, r"/test_dir/file_1\.txt:extension$|/test_dir_2/extension_alias\.txt(:extension)?$")
    assert "/test_dir/file_1.txt:extension" in result
    assert "/test_dir_2/extension_alias.txt" in result
    assert "/test_dir_2/extension_alias.txt:extension" in result


def test_mft_only_search_reports_external_list_data_unavailable(
    nonresident_attribute_list_image,
):
    image_path, _, _ = nonresident_attribute_list_image
    image = pytsk3.Img_Info(str(image_path))
    try:
        table = pytsk3.Volume_Info(image)
        partition = next(part for part in table if b"NTFS" in part.desc)
        filesystem = pytsk3.FS_Info(image, partition.start * table.info.block_size)
        mft_file = filesystem.open("/$MFT")
        mft = mft_file.read_random(0, mft_file.info.meta.size)
    finally:
        image.close()
    with pytest.raises(NtfsDumpError, match="nonresident.*ATTRIBUTE_LIST.*unavailable"):
        find_records(mft, re.compile("extension_alias"), False)


def test_image_json_reports_extension_stream_size_and_aliases(
    nonresident_attribute_list_image,
):
    image_path, _, _ = nonresident_attribute_list_image
    rows = [
        json.loads(line)
        for line in ntfsfind(
            image_path,
            r"/file_1\.txt:extension$|/extension_alias\.txt(:extension)?$",
            output_format="json",
        )
    ]
    by_path = {row["path"]: row for row in rows}
    assert by_path["/test_dir/file_1.txt:extension"]["size"] == 16
    assert "/test_dir_2/extension_alias.txt" in by_path
    assert by_path["/test_dir_2/extension_alias.txt:extension"]["size"] == 16


def test_mft_export_only_succeeds_for_external_attribute_list(
    nonresident_attribute_list_image, tmp_path, capsys
):
    from ntfsfind.cli import main

    image_path, _, _ = nonresident_attribute_list_image
    image = pytsk3.Img_Info(str(image_path))
    try:
        table = pytsk3.Volume_Info(image)
        partition = next(part for part in table if b"NTFS" in part.desc)
        filesystem = pytsk3.FS_Info(image, partition.start * table.info.block_size)
        mft_file = filesystem.open("/$MFT")
        mft = mft_file.read_random(0, mft_file.info.meta.size)
    finally:
        image.close()
    source = tmp_path / "source.mft"
    exported = tmp_path / "exported.mft"
    source.write_bytes(mft)
    assert main(["--out-mft", str(exported), str(source)]) == 0
    assert exported.read_bytes() == mft
    assert capsys.readouterr().out == ""


def test_cli_external_list_error_has_no_partial_output(
    nonresident_attribute_list_image, tmp_path, capsys
):
    from ntfsfind.cli import main

    image_path, _, _ = nonresident_attribute_list_image
    image = pytsk3.Img_Info(str(image_path))
    try:
        table = pytsk3.Volume_Info(image)
        partition = next(part for part in table if b"NTFS" in part.desc)
        filesystem = pytsk3.FS_Info(image, partition.start * table.info.block_size)
        mft_file = filesystem.open("/$MFT")
        mft = mft_file.read_random(0, mft_file.info.meta.size)
    finally:
        image.close()
    source = tmp_path / "source.mft"
    source.write_bytes(mft)
    assert main([str(source), "extension_alias"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "attribute_list" in captured.err.lower()


def test_stale_extension_sequence_in_nonresident_list_is_ignored(
    nonresident_attribute_list_image,
):
    image_path, list_value, offsets = nonresident_attribute_list_image
    stale = bytearray(list_value)
    cursor = 0
    changed = 0
    while cursor < len(stale):
        type_code, size = struct.unpack_from("<IH", stale, cursor)
        reference = struct.unpack_from("<Q", stale, cursor + 16)[0]
        if reference & ((1 << 48) - 1) == 100:
            struct.pack_into("<Q", stale, cursor + 16, 100 | 99 << 48)
            changed += 1
        cursor += size
    assert changed == 2
    with _temporary_image_bytes(image_path, offsets["list_offset"], stale):
        results = ntfsfind(image_path, "extension_alias|:extension$")
    assert results == []


def test_stale_extension_base_reference_is_ignored(nonresident_attribute_list_image):
    image_path, _, offsets = nonresident_attribute_list_image
    stale_reference = struct.pack("<Q", 52 | 99 << 48)
    with _temporary_image_bytes(
        image_path, offsets["extension_record_offset"] + 32, stale_reference
    ):
        results = ntfsfind(image_path, "extension_alias|:extension$")
    assert results == []
