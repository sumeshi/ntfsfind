"""A checksum-verified real NTFS sample for the native parser integration tests."""

import hashlib
import os
from pathlib import Path
import tarfile
from urllib.request import urlopen

import pytest

SAMPLE_URL = "https://github.com/msuhanov/ntfs-samples/blob/master/ntfs.tgz?raw=true"
SAMPLE_SHA256 = "06d69d832f911bd3e09b8331d8d48e1d44a0ad82fdf034addf7d14811ed57db0"


@pytest.fixture(scope="session")
def ntfs_sample(tmp_path_factory):
    archive = Path(
        os.environ.get(
            "NTFS_SAMPLE_ARCHIVE", str(Path(__file__).parent / "cache" / "ntfs.tgs")
        )
    )
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(SAMPLE_URL, timeout=120) as response:
            data = response.read()
        assert hashlib.sha256(data).hexdigest() == SAMPLE_SHA256
        archive.write_bytes(data)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == SAMPLE_SHA256

    destination = tmp_path_factory.mktemp("ntfs-sample")
    with tarfile.open(archive, "r:gz") as compressed:
        member = compressed.getmember("ntfs.raw")
        assert member.isfile()
        compressed.extract(member, destination, filter="data")
    return destination / "ntfs.raw"
