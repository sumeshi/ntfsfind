import errno
import os
from pathlib import Path

import pytest

from ntfsdump.errors import NtfsDumpError
from ntfsfind import core
from ntfsfind.export import export_mft


def test_export_publishes_complete_content(tmp_path):
    destination = tmp_path / "export.mft"
    export_mft(destination, b"FILE" + b"content" * 100)
    assert destination.read_bytes() == b"FILE" + b"content" * 100
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("alias", ["same", "hardlink", "symlink", "other"])
def test_export_never_overwrites_existing_files(tmp_path, alias, monkeypatch):
    evidence = tmp_path / "evidence.raw"
    evidence.write_bytes(b"original evidence")
    destination = evidence
    if alias != "same":
        destination = tmp_path / "output.mft"
        if alias == "hardlink":
            os.link(evidence, destination)
        elif alias == "symlink":
            try:
                destination.symlink_to(evidence)
            except OSError:
                pytest.skip("Host does not permit symlink creation")
        else:
            destination.write_bytes(b"previous export")
    before = destination.read_bytes()

    def unexpected_read(*args, **kwargs):
        pytest.fail("Existing output must be rejected before reading an image")

    monkeypatch.setattr(core, "ImageFile", unexpected_read)
    with pytest.raises(NtfsDumpError, match="already exists"):
        core.ntfsfind(evidence, out_mft=str(destination))
    assert evidence.read_bytes() == b"original evidence"
    assert destination.read_bytes() == before


def test_export_preserves_destination_created_during_write(tmp_path, monkeypatch):
    destination = tmp_path / "output.mft"
    real_link = os.link

    def raced_link(source, target):
        Path(target).write_bytes(b"another process wrote this")
        return real_link(source, target)

    monkeypatch.setattr(os, "link", raced_link)
    with pytest.raises(NtfsDumpError, match="already exists"):
        export_mft(destination, b"FILEdata")
    assert destination.read_bytes() == b"another process wrote this"
    assert list(tmp_path.iterdir()) == [destination]


def test_export_failure_leaves_no_partial_output(tmp_path, monkeypatch):
    def failed_sync(fd):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", failed_sync)
    with pytest.raises(OSError, match="disk full"):
        export_mft(tmp_path / "output.mft", b"FILEdata")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "number", [errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS]
)
def test_export_works_without_hard_link_support(tmp_path, monkeypatch, number):
    destination = tmp_path / "export.mft"
    content = b"FILE" + b"export content" * 10000

    def unsupported_link(source, target):
        raise OSError(number, "Hard links are not supported")

    monkeypatch.setattr(os, "link", unsupported_link)
    export_mft(destination, content)
    assert destination.read_bytes() == content
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("winerror", [1, 50])
def test_export_handles_windows_unsupported_link_error(tmp_path, monkeypatch, winerror):
    failure = OSError(errno.EINVAL, "Unsupported Windows filesystem")
    failure.winerror = winerror

    def unsupported_link(source, target):
        raise failure

    monkeypatch.setattr(os, "link", unsupported_link)
    destination = tmp_path / "export.mft"
    export_mft(destination, b"FILEdata")
    assert destination.read_bytes() == b"FILEdata"


@pytest.mark.parametrize("alias", ["file", "symlink"])
def test_export_without_links_preserves_raced_destination(tmp_path, monkeypatch, alias):
    destination = tmp_path / "export.mft"
    evidence = tmp_path / "evidence.raw"
    evidence.write_bytes(b"original evidence")

    def unsupported_link(source, target):
        if alias == "file":
            destination.write_bytes(b"another process wrote this")
        else:
            try:
                destination.symlink_to(evidence)
            except OSError:
                pytest.skip("Host does not permit symlink creation")
        raise OSError(errno.EOPNOTSUPP, "Hard links are not supported")

    monkeypatch.setattr(os, "link", unsupported_link)
    with pytest.raises(NtfsDumpError, match="already exists"):
        export_mft(destination, b"FILEdata")
    expected = (
        b"another process wrote this" if alias == "file" else evidence.read_bytes()
    )
    assert destination.read_bytes() == expected
    assert evidence.read_bytes() == b"original evidence"
    assert not list(tmp_path.glob(".ntfsfind-*.tmp"))


@pytest.mark.parametrize("replace_failed_output", [False, True])
def test_export_without_links_cleans_only_its_failed_output(
    tmp_path, monkeypatch, replace_failed_output
):
    destination = tmp_path / "export.mft"
    real_sync = os.fsync
    sync_calls = 0

    def unsupported_link(source, target):
        raise OSError(errno.EOPNOTSUPP, "Hard links are not supported")

    def failed_final_sync(fd):
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 2:
            raise OSError("disk full")
        return real_sync(fd)

    if replace_failed_output:
        real_lstat = Path.lstat

        def replace_before_cleanup(path, *args, **kwargs):
            if path == destination:
                replacement = tmp_path / "replacement"
                replacement.write_bytes(b"another process wrote this")
                replacement.replace(destination)
            return real_lstat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "lstat", replace_before_cleanup)

    monkeypatch.setattr(os, "link", unsupported_link)
    monkeypatch.setattr(os, "fsync", failed_final_sync)
    with pytest.raises(OSError, match="disk full"):
        export_mft(destination, b"FILEdata")
    if replace_failed_output:
        assert destination.read_bytes() == b"another process wrote this"
        assert list(tmp_path.iterdir()) == [destination]
    else:
        assert list(tmp_path.iterdir()) == []


def test_export_does_not_hide_unrelated_link_failure(tmp_path, monkeypatch):
    def failed_link(source, target):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "link", failed_link)
    with pytest.raises(OSError, match="I/O error"):
        export_mft(tmp_path / "output.mft", b"FILEdata")
    assert list(tmp_path.iterdir()) == []
