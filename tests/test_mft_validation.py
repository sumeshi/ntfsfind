"""Incomplete MFT input must not silently become an empty/successful search."""

import io
import re
import struct

import pytest
from mft import PyMftParser
from ntfsdump.errors import NtfsDumpError

from ntfsfind import core
from ntfsfind.cli import main
from ntfsfind.mft_validation import validate_mft_layout


@pytest.fixture(scope="module")
def real_mft(ntfs_sample, tmp_path_factory):
    destination = tmp_path_factory.mktemp("mft-validation") / "export.mft"
    core.ntfsfind(ntfs_sample, out_mft=str(destination))
    return destination.read_bytes()


@pytest.mark.parametrize("length", [0, 4, 31, 32, 48, 1023, 1025])
def test_native_search_rejects_incomplete_records(real_mft, length):
    with pytest.raises(NtfsDumpError, match="Incomplete MFT"):
        core.find_records(real_mft[:length], re.compile("."), False)


@pytest.mark.parametrize("size", [0, 128, 511, 1000, 1025, 131072, 0xFFFFFFFF])
def test_search_rejects_invalid_record_size_before_native_parser(real_mft, size):
    malformed = bytearray(real_mft)
    struct.pack_into("<I", malformed, 28, size)
    with pytest.raises(NtfsDumpError, match="Invalid MFT record size"):
        core.find_records(bytes(malformed), re.compile("."), False)


def test_complete_real_mft_remains_searchable(real_mft):
    assert "/test_dir/file_1.txt" in core.find_records(
        real_mft, re.compile("file_1"), False
    )


def test_complete_4096_byte_native_record(real_mft):
    # Reframe a genuine record into a 4096-byte record, retaining its
    # attributes and constructing the update sequence for all eight sectors.
    original = bytearray(real_mft[:1024])
    usa_offset, usa_count = struct.unpack_from("<HH", original, 4)
    for sector in range(1, usa_count):
        original[sector * 512 - 2 : sector * 512] = original[
            usa_offset + sector * 2 : usa_offset + sector * 2 + 2
        ]
    attributes = struct.unpack_from("<H", original, 20)[0]
    used_size = struct.unpack_from("<I", original, 24)[0]
    record = bytearray(4096)
    record[:48] = original[:48]
    record[72 : 72 + used_size - attributes] = original[attributes:used_size]
    struct.pack_into("<HH", record, 4, 48, 9)
    struct.pack_into("<H", record, 20, 72)
    struct.pack_into("<II", record, 24, 72 + used_size - attributes, 4096)
    record[48:50] = b"\xfe\xad"
    for sector in range(1, 9):
        record[48 + sector * 2 : 50 + sector * 2] = record[
            sector * 512 - 2 : sector * 512
        ]
        record[sector * 512 - 2 : sector * 512] = record[48:50]
    content = bytes(record)
    assert len(list(PyMftParser(io.BytesIO(content)).entries())) == 1
    # This isolated record has no parent root record to validate its path.
    assert core.find_records(content, re.compile(r"\$MFT$"), False) == [
        "/[UNKNOWN]/$MFT"
    ]
    with pytest.raises(NtfsDumpError, match="Incomplete MFT"):
        core.find_records(content[:-1], None, False)


def test_cli_reports_truncated_search_but_preserves_export_only(
    real_mft, tmp_path, capsys
):
    source = tmp_path / "truncated.mft"
    source.write_bytes(real_mft[:1025])
    assert main([str(source), "."]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Incomplete MFT" in captured.err

    # Export-only is deliberately a byte-for-byte operation, with no search.
    destination = tmp_path / "copied.mft"
    assert main([str(source), "--out-mft", str(destination)]) == 0
    assert destination.read_bytes() == source.read_bytes()


def test_invalid_signature_is_rejected():
    with pytest.raises(NtfsDumpError, match="signature"):
        core.find_records(bytes(1024), None, False)
