"""Native NTFS volume images must work with the independently published backend."""

from hashlib import md5

import pytsk3
import pytest

from ntfsdump.errors import NtfsDumpError
from ntfsfind.core import ntfsfind
from ntfsfind.image import _find_ntfs_volumes, _is_backend_selection_error, read_image_mft


@pytest.fixture(scope="session")
def ntfs_volume_image(ntfs_sample, tmp_path_factory):
    image = pytsk3.Img_Info(str(ntfs_sample))
    try:
        table = pytsk3.Volume_Info(image)
        partition = next(item for item in table if b"NTFS" in item.desc)
        sector = table.info.block_size
        start = partition.start * sector
        length = partition.len * sector
        filesystem = pytsk3.FS_Info(image, start, pytsk3.TSK_FS_TYPE_NTFS)
        # Retain real boot/MFT/root-index metadata in a sparse partition slice.
        # Search reads the MFT, so copying every file's content is unnecessary.
        # Ordinary seek/write/truncate keeps the fixture portable to Windows.
        ranges = [(0, 1024 * 1024), (length - sector, sector)]
        for query in ("/$MFT", "/"):
            for attribute in filesystem.open(query):
                for run in attribute:
                    if run.addr:
                        ranges.append(
                            (
                                run.addr * filesystem.info.block_size,
                                run.len * filesystem.info.block_size,
                            )
                        )
        destination = tmp_path_factory.mktemp("ntfs-volume") / "volume.raw"
        with ntfs_sample.open("rb") as source, destination.open("wb") as output:
            output.truncate(length)
            for offset, size in ranges:
                source.seek(start + offset)
                output.seek(offset)
                output.write(source.read(size))
        return destination
    finally:
        image.close()


def test_native_standalone_volume_search(ntfs_volume_image, ntfs_sample):
    disk_records = ntfsfind(ntfs_sample, path="/")
    assert disk_records
    assert ntfsfind(ntfs_volume_image, path="/") == disk_records
    assert ntfsfind(ntfs_volume_image, path="/", volume=0) == disk_records


def test_native_standalone_volume_export(ntfs_volume_image, tmp_path):
    destination = tmp_path / "export.mft"
    size = ntfs_volume_image.stat().st_size
    ntfsfind(ntfs_volume_image, out_mft=str(destination), image_format="raw")
    assert (
        md5(destination.read_bytes()).hexdigest() == "edb7605e808ec25c8e5feea382a49047"
    )
    assert ntfs_volume_image.stat().st_size == size


def test_standalone_volume_rejects_nonzero_volume(ntfs_volume_image):
    with pytest.raises(NtfsDumpError, match="NTFS volume 2 was not found"):
        ntfsfind(ntfs_volume_image, path="/", volume=2)


def test_offset_zero_fallback_requires_real_ntfs(tmp_path):
    invalid = tmp_path / "invalid.raw"
    invalid.write_bytes(bytes(4096))
    original = OSError("partition table parse failed")

    def failed_backend(*args, **kwargs):
        raise original

    with pytest.raises(OSError) as raised:
        read_image_mft(invalid, failed_backend)
    assert raised.value is original


def test_no_ntfs_candidates_can_fall_back_to_verified_volume(ntfs_volume_image):
    def table_without_ntfs(*args, **kwargs):
        raise NtfsDumpError("No NTFS volume was found.")

    content = read_image_mft(ntfs_volume_image, table_without_ntfs)
    assert md5(content).hexdigest() == "edb7605e808ec25c8e5feea382a49047"


def test_fallback_does_not_hide_other_backend_errors(ntfs_volume_image):
    error = NtfsDumpError("Multiple virtual disks were found.")

    def ambiguous_backend(*args, **kwargs):
        raise error

    with pytest.raises(NtfsDumpError) as raised:
        read_image_mft(ntfs_volume_image, ambiguous_backend)
    assert raised.value is error


@pytest.mark.parametrize(
    "message",
    [
        "No NTFS volume was found.",
        "NTFS volume 4 was not found.",
        "Multiple NTFS volumes were found, but none of them looks like a Windows OS volume",
    ],
)
def test_legacy_partition_selection_errors_allow_native_scan(message):
    assert _is_backend_selection_error(NtfsDumpError(message))


def test_native_scan_probes_allocated_user_labeled_partition(monkeypatch):
    class Part:
        def __init__(self, addr, start, flags, desc):
            self.addr = addr
            self.start = start
            self.len = 10
            self.flags = flags
            self.desc = desc

    class Table(list):
        info = type("Info", (), {"block_size": 512})()

    table = Table(
        [
            Part(1, 0, pytsk3.TSK_VS_PART_FLAG_META, b"GPT Header"),
            Part(4, 256, pytsk3.TSK_VS_PART_FLAG_ALLOC, b"Evidence"),
        ]
    )
    filesystem = object()
    offsets = []
    monkeypatch.setattr(pytsk3, "Volume_Info", lambda image: table)

    def fs_info(image, offset, fs_type):
        offsets.append(offset)
        return filesystem

    monkeypatch.setattr(pytsk3, "FS_Info", fs_info)
    image = type(
        "Image", (), {"logical_sector_size": 4096, "handle": object()}
    )()
    found = _find_ntfs_volumes(image)
    assert offsets == [256 * 4096]
    assert [(addr, description, fs) for addr, description, fs in found] == [
        (4, "Evidence", filesystem)
    ]
