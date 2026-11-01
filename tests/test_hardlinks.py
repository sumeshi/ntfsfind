"""Search real MFT hardlinks through each FILE_NAME's parent reference."""

from datetime import datetime, timezone
import io
import json
import re
import struct

from mft import PyMftParser
import pytsk3
import pytest

from ntfsfind.core import find_records
from ntfsfind.filters import build_filters
from ntfsfind.record import iter_records


@pytest.fixture(scope="module")
def native_mft(ntfs_sample):
    image = pytsk3.Img_Info(str(ntfs_sample))
    try:
        volumes = pytsk3.Volume_Info(image)
        partition = next(p for p in volumes if p.desc.startswith(b"NTFS"))
        fs = pytsk3.FS_Info(image, partition.start * volumes.info.block_size)
        source = fs.open("/$MFT")
        return source.read_random(0, source.info.meta.size)
    finally:
        image.close()


def add_link(raw, name, parent=50, parent_sequence=2, namespace=0, ads=False):
    """Add native resident attributes, maintaining NTFS sector fixups."""
    result = bytearray(raw)
    start = 52 * 1024
    record = bytearray(result[start : start + 1024])
    usa_offset, usa_count = struct.unpack_from("<HH", record, 4)
    marker = record[usa_offset : usa_offset + 2]
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        assert record[offset : offset + 2] == marker
        record[offset : offset + 2] = record[
            usa_offset + sector * 2 : usa_offset + sector * 2 + 2
        ]

    position = struct.unpack_from("<H", record, 20)[0]
    filename = None
    while struct.unpack_from("<I", record, position)[0] != 0xFFFFFFFF:
        code, size = struct.unpack_from("<II", record, position)
        if code == 48:
            filename = bytearray(record[position : position + size])
        position += size
    assert filename is not None
    value_offset = struct.unpack_from("<H", filename, 20)[0]
    name_bytes = name.encode("utf-16le")
    value_size = 66 + len(name_bytes)
    attribute_size = (value_offset + value_size + 7) // 8 * 8
    filename = filename[: value_offset + 66] + name_bytes
    filename.extend(bytes(attribute_size - len(filename)))
    struct.pack_into("<I", filename, 4, attribute_size)
    struct.pack_into("<H", filename, 14, 5)
    struct.pack_into("<I", filename, 16, value_size)
    struct.pack_into("<Q", filename, value_offset, parent | parent_sequence << 48)
    # 2024-01-01T00:00:00Z, distinct from the original name's 2020 timestamp.
    struct.pack_into("<Q", filename, value_offset + 8, 133485408000000000)
    filename[value_offset + 64] = len(name_bytes) // 2
    filename[value_offset + 65] = namespace
    attributes = [filename]
    if ads:
        stream = bytearray(40)
        struct.pack_into("<IIBBHHH", stream, 0, 128, 40, 0, 3, 24, 0, 6)
        struct.pack_into("<IHBB", stream, 16, 4, 32, 0, 0)
        stream[24:30] = "ads".encode("utf-16le")
        stream[32:36] = b"data"
        attributes.append(stream)
    for attribute in attributes:
        record[position : position + len(attribute)] = attribute
        position += len(attribute)
    assert position + 8 < 1024
    struct.pack_into("<II", record, position, 0xFFFFFFFF, 0)
    struct.pack_into("<I", record, 24, position + 8)
    struct.pack_into("<H", record, 18, 2)
    struct.pack_into("<H", record, 40, 7 if ads else 6)
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        record[usa_offset + sector * 2 : usa_offset + sector * 2 + 2] = record[
            offset : offset + 2
        ]
        record[offset : offset + 2] = marker
    result[start : start + 1024] = record
    return bytes(result)


def add_extension_stream(raw):
    """Move a named DATA stream to a valid extension record and list it."""
    start = 52 * 1024
    source = bytearray(raw[start : start + 1024])
    usa_offset, usa_count = struct.unpack_from("<HH", source, 4)
    marker = source[usa_offset : usa_offset + 2]
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        source[offset : offset + 2] = source[
            usa_offset + sector * 2 : usa_offset + sector * 2 + 2
        ]
    position = struct.unpack_from("<H", source, 20)[0]
    attributes = []
    while struct.unpack_from("<I", source, position)[0] != 0xFFFFFFFF:
        length = struct.unpack_from("<I", source, position + 4)[0]
        attributes.append(bytes(source[position : position + length]))
        position += length

    def resident(type_code, attr_id, name, value):
        encoded = name.encode("utf-16le")
        value_offset = (24 + len(encoded) + 7) // 8 * 8
        size = (value_offset + len(value) + 7) // 8 * 8
        result = bytearray(size)
        struct.pack_into(
            "<IIBBHHH",
            result,
            0,
            type_code,
            size,
            0,
            len(name),
            24 if encoded else 0,
            0,
            attr_id,
        )
        struct.pack_into("<IHBB", result, 16, len(value), value_offset, 0, 0)
        result[24 : 24 + len(encoded)] = encoded
        result[value_offset : value_offset + len(value)] = value
        return bytes(result)

    def list_entry(type_code, name, entry_id, sequence, attr_id):
        encoded = name.encode("utf-16le")
        size = (26 + len(encoded) + 7) // 8 * 8
        result = bytearray(size)
        struct.pack_into(
            "<IHBBQQH",
            result,
            0,
            type_code,
            size,
            len(name),
            26 if encoded else 0,
            0,
            entry_id | sequence << 48,
            attr_id,
        )
        result[26 : 26 + len(encoded)] = encoded
        return bytes(result)

    list_value = bytearray()
    for attribute in attributes:
        code = struct.unpack_from("<I", attribute, 0)[0]
        attr_id = struct.unpack_from("<H", attribute, 14)[0]
        list_value += list_entry(code, "", 52, 1, attr_id)
    alias_name = "extension_alias.txt"
    alias_bytes = alias_name.encode("utf-16le")
    filename_value = bytearray(66 + len(alias_bytes))
    struct.pack_into("<Q", filename_value, 0, 64 | 1 << 48)
    filename_value[64] = len(alias_name)
    filename_value[65] = 1
    filename_value[66:] = alias_bytes
    attributes.append(resident(48, 6, "", filename_value))
    list_value += list_entry(48, "", 100, 1, 6)
    list_value += list_entry(128, "extension", 100, 1, 5)
    attributes.append(resident(32, 7, "", list_value))

    def make_record(record_attributes, entry_id, base_reference=0):
        result = bytearray(1024)
        result[:position] = source[:position]
        struct.pack_into("<Q", result, 32, base_reference)
        struct.pack_into("<I", result, 44, entry_id)
        struct.pack_into("<H", result, 18, 0 if base_reference else 1)
        cursor = struct.unpack_from("<H", result, 20)[0]
        for attribute in record_attributes:
            result[cursor : cursor + len(attribute)] = attribute
            cursor += len(attribute)
        struct.pack_into("<II", result, cursor, 0xFFFFFFFF, 0)
        struct.pack_into("<I", result, 24, cursor + 8)
        struct.pack_into("<H", result, 40, 8)
        for sector in range(1, usa_count):
            offset = sector * 512 - 2
            result[usa_offset + sector * 2 : usa_offset + sector * 2 + 2] = result[
                offset : offset + 2
            ]
            result[offset : offset + 2] = marker
        return bytes(result)

    extension = make_record(
        [
            resident(48, 6, "", filename_value),
            resident(128, 5, "extension", b"EXTENSION STREAM"),
        ],
        100,
        52 | 1 << 48,
    )
    modified = bytearray(raw)
    modified[start : start + 1024] = make_record(attributes, 52)
    modified[100 * 1024 : 101 * 1024] = extension
    return bytes(modified)


def rename_directory_with_trailing_space(raw):
    """Change test_dir to an equal-length name ending in a space."""
    modified = bytearray(raw)
    start = 50 * 1024
    record = bytearray(modified[start : start + 1024])
    usa_offset, usa_count = struct.unpack_from("<HH", record, 4)
    marker = record[usa_offset : usa_offset + 2]
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        record[offset : offset + 2] = record[
            usa_offset + sector * 2 : usa_offset + sector * 2 + 2
        ]
    position = struct.unpack_from("<H", record, 20)[0]
    while struct.unpack_from("<I", record, position)[0] != 0xFFFFFFFF:
        code, length = struct.unpack_from("<II", record, position)
        if code == 48:
            value_offset = struct.unpack_from("<H", record, position + 20)[0]
            value_start = position + value_offset
            name_length = record[value_start + 64]
            name = record[value_start + 66 : value_start + 66 + name_length * 2]
            if name.decode("utf-16le") == "test_dir":
                record[value_start + 66 : value_start + 66 + name_length * 2] = (
                    "test_di ".encode("utf-16le")
                )
        position += length
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        record[usa_offset + sector * 2 : usa_offset + sector * 2 + 2] = record[
            offset : offset + 2
        ]
        record[offset : offset + 2] = marker
    modified[start : start + 1024] = record
    return bytes(modified)


def make_directory_parent_sequence_stale(raw):
    """Point test_dir at record 64 with a stale expected sequence."""
    modified = bytearray(raw)
    start = 50 * 1024
    record = bytearray(modified[start : start + 1024])
    usa_offset, usa_count = struct.unpack_from("<HH", record, 4)
    marker = record[usa_offset : usa_offset + 2]
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        record[offset : offset + 2] = record[
            usa_offset + sector * 2 : usa_offset + sector * 2 + 2
        ]
    position = struct.unpack_from("<H", record, 20)[0]
    while struct.unpack_from("<I", record, position)[0] != 0xFFFFFFFF:
        code, length = struct.unpack_from("<II", record, position)
        if code == 48:
            value_offset = struct.unpack_from("<H", record, position + 20)[0]
            value_start = position + value_offset
            if (
                record[value_start + 66 : value_start + 82].decode("utf-16le")
                == "test_dir"
            ):
                struct.pack_into("<Q", record, value_start, 64 | 99 << 48)
        position += length
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        record[usa_offset + sector * 2 : usa_offset + sector * 2 + 2] = record[
            offset : offset + 2
        ]
        record[offset : offset + 2] = marker
    modified[start : start + 1024] = record
    return bytes(modified)


def make_filename_parent_reference_stale(raw, entry_id, name, parent, sequence):
    """Change one FILE_NAME parent reference while preserving sector fixups."""
    modified = bytearray(raw)
    start = entry_id * 1024
    record = bytearray(modified[start : start + 1024])
    usa_offset, usa_count = struct.unpack_from("<HH", record, 4)
    marker = record[usa_offset : usa_offset + 2]
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        record[offset : offset + 2] = record[
            usa_offset + sector * 2 : usa_offset + sector * 2 + 2
        ]
    position = struct.unpack_from("<H", record, 20)[0]
    found = False
    while struct.unpack_from("<I", record, position)[0] != 0xFFFFFFFF:
        code, length = struct.unpack_from("<II", record, position)
        if code == 48:
            value_offset = struct.unpack_from("<H", record, position + 20)[0]
            value_start = position + value_offset
            name_length = record[value_start + 64]
            filename = record[
                value_start + 66 : value_start + 66 + name_length * 2
            ].decode("utf-16le")
            if filename == name:
                struct.pack_into("<Q", record, value_start, parent | sequence << 48)
                found = True
        position += length
    assert found
    for sector in range(1, usa_count):
        offset = sector * 512 - 2
        record[usa_offset + sector * 2 : usa_offset + sector * 2 + 2] = record[
            offset : offset + 2
        ]
        record[offset : offset + 2] = marker
    modified[start : start + 1024] = record
    return bytes(modified)


@pytest.mark.parametrize(
    "parent, sequence, directory", [(50, 2, "test_dir"), (64, 1, "test_dir_2")]
)
def test_searches_hardlink_alias_in_its_own_parent(
    native_mft, parent, sequence, directory
):
    modified = add_link(native_mft, "alias1.txt", parent, sequence)
    assert find_records(modified, re.compile(r"alias1\.txt$"), False) == [
        f"/{directory}/alias1.txt"
    ]
    assert find_records(modified, re.compile(r"/file_1\.txt$"), False) == [
        "/test_dir/file_1.txt"
    ]


def test_alias_uses_its_filename_timestamp_and_shares_streams(native_mft):
    modified = add_link(
        native_mft, "alias1.txt", parent=64, parent_sequence=1, ads=True
    )
    rows = [
        json.loads(line)
        for line in find_records(
            modified,
            re.compile(r"/(alias1|file_1)\.txt(:ads)?$"),
            False,
            output_format="json",
        )
    ]
    assert {row["path"] for row in rows} == {
        "/test_dir/file_1.txt",
        "/test_dir/file_1.txt:ads",
        "/test_dir_2/alias1.txt",
        "/test_dir_2/alias1.txt:ads",
    }
    alias_rows = [row for row in rows if "alias1" in row["path"]]
    assert all(
        row["fn"]["created"] == "2024-01-01T00:00:00+00:00" for row in alias_rows
    )
    assert all(row["entry_id"] == 52 for row in rows)
    entries = PyMftParser(io.BytesIO(modified)).entries()
    records = [record for record in iter_records(entries) if record.entry_id == 52]
    assert all(record.hard_link_count == 2 for record in records)
    assert [record.fn_created for record in records if "alias1" in record.path] == [
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 1, 1, tzinfo=timezone.utc),
    ]


def test_dos_short_name_does_not_duplicate_long_name(native_mft):
    modified = add_link(native_mft, "FILE_1~1.TXT", namespace=2)
    entries = PyMftParser(io.BytesIO(modified)).entries()
    assert [
        record.path for record in iter_records(entries) if record.entry_id == 52
    ] == ["/test_dir/file_1.txt"]


def test_reused_parent_does_not_attach_alias_to_unrelated_directory(native_mft):
    modified = add_link(native_mft, "alias1.txt", parent=64, parent_sequence=99)
    paths = find_records(modified, re.compile("alias1"), False)
    assert paths == ["/[UNKNOWN]/alias1.txt"]
    assert "/test_dir_2/alias1.txt" not in paths


def test_unmodified_sample_keeps_existing_result_count(native_mft):
    assert len(find_records(native_mft, re.compile("."), False)) == 102


def test_extension_stream_is_joined_to_its_base_record(native_mft):
    modified = add_extension_stream(native_mft)
    assert find_records(
        modified, re.compile(r"/test_dir/file_1\.txt:extension$"), False
    ) == ["/test_dir/file_1.txt:extension"]
    assert find_records(
        modified, re.compile(r"/test_dir_2/extension_alias\.txt(:extension)?$"), False
    ) == [
        "/test_dir_2/extension_alias.txt",
        "/test_dir_2/extension_alias.txt:extension",
    ]
    assert find_records(
        modified,
        None,
        False,
        filters=build_filters(path="/test_dir", ads_only=True),
    ) == ["/test_dir/file_1.txt:extension"]


def test_path_filter_preserves_trailing_space(native_mft):
    modified = rename_directory_with_trailing_space(native_mft)
    paths = find_records(modified, None, False, filters=build_filters(path="/test_di "))
    assert len([path for path in paths if "/file_" in path]) == 12
    assert "/test_di /file_1.txt" in paths
    assert not find_records(
        modified, None, False, filters=build_filters(path="/test_di")
    )


def test_stale_ancestor_sequence_does_not_leak_parser_path(native_mft):
    modified = make_directory_parent_sequence_stale(native_mft)
    paths = find_records(modified, re.compile(r"/file_1\.txt$"), False)
    assert paths == ["/[UNKNOWN]/test_dir/file_1.txt"]


def test_stale_root_parent_sequence_marks_directory_and_descendants_unknown(
    native_mft,
):
    modified = make_filename_parent_reference_stale(
        native_mft, entry_id=50, name="test_dir", parent=5, sequence=99
    )
    paths = find_records(modified, re.compile(r"/test_dir(/|$)|/file_1\.txt$"), False)
    assert "/[UNKNOWN]/test_dir" in paths
    assert "/[UNKNOWN]/test_dir/file_1.txt" in paths
    assert "/test_dir" not in paths
    assert "/test_dir/file_1.txt" not in paths


def test_stale_root_parent_sequence_marks_root_child_file_unknown(native_mft):
    modified = add_link(native_mft, "root_alias.txt", parent=5, parent_sequence=99)
    assert find_records(modified, re.compile(r"root_alias\.txt$"), False) == [
        "/[UNKNOWN]/root_alias.txt"
    ]


def test_missing_root_record_marks_root_children_and_descendants_unknown(native_mft):
    entries = PyMftParser(io.BytesIO(native_mft)).entries()
    records = list(iter_records(entry for entry in entries if entry.entry_id != 5))
    assert "/[UNKNOWN]/test_dir" in {
        record.path for record in records if record.entry_id == 50
    }
    assert "/[UNKNOWN]/test_dir/file_1.txt" in {
        record.path for record in records if record.entry_id == 52
    }


def test_non_directory_root_marks_root_children_and_descendants_unknown(native_mft):
    entries = PyMftParser(io.BytesIO(native_mft)).entries()

    class NonDirectoryRoot:
        def __init__(self, entry):
            self.entry = entry

        def __getattr__(self, name):
            if name == "flags_value":
                return None
            if name == "flags":
                return "ALLOCATED"
            return getattr(self.entry, name)

        def attributes(self):
            return self.entry.attributes()

    entries = [
        NonDirectoryRoot(entry) if entry.entry_id == 5 else entry for entry in entries
    ]
    records = list(iter_records(entries))
    assert "/[UNKNOWN]/test_dir" in {
        record.path for record in records if record.entry_id == 50
    }
    assert "/[UNKNOWN]/test_dir/file_1.txt" in {
        record.path for record in records if record.entry_id == 52
    }
