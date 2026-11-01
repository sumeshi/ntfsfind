import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

import pytest

from ntfsdump.errors import NtfsDumpError
from ntfsfind import core


def test_real_root_path_lists_records(ntfs_sample):
    matches = core.ntfsfind(ntfs_sample, path="/")
    assert matches == core.ntfsfind(ntfs_sample, search_query=".")
    assert "/$MFT" in matches
    assert "/test_dir/file_1.txt" in matches


def test_real_root_regex_matches_canonical_root(ntfs_sample, tmp_path):
    exported_mft = tmp_path / "export.mft"
    core.ntfsfind(ntfs_sample, out_mft=str(exported_mft))

    for source in (ntfs_sample, exported_mft):
        assert core.ntfsfind(source, search_query=r"^/$") == ["/"]
        records = [
            json.loads(line)
            for line in core.ntfsfind(source, search_query=r"^/$", output_format="json")
        ]
        assert len(records) == 1
        assert records[0]["path"] == "/"
        assert records[0]["entry_id"] == 5
        assert records[0]["dir"]


def test_real_filter_metadata_and_day_upper_bound(ntfs_sample):
    matches = core.ntfsfind(
        ntfs_sample,
        path="/test_dir",
        extension="txt",
        size="6",
        created="<=2020-07-25",
        output_format="json",
    )
    records = [json.loads(line) for line in matches]
    assert {record["path"] for record in records} == {
        "/test_dir/file_1.txt",
        "/test_dir/file_2.txt",
        "/test_dir/file_8.txt",
    }
    assert all(record["allocated"] for record in records)
    assert all(record["size"] == 6 for record in records)
    directory = json.loads(
        core.ntfsfind(
            ntfs_sample,
            search_query="^/test_dir$",
            output_format="json",
        )[0]
    )
    assert directory["file_flags"] == []


def test_real_mft_export_and_standalone_search(ntfs_sample, tmp_path):
    destination = tmp_path / "export.mft"
    original_size = ntfs_sample.stat().st_size
    core.ntfsfind(ntfs_sample, out_mft=str(destination))
    assert (
        hashlib.md5(destination.read_bytes()).hexdigest()
        == "edb7605e808ec25c8e5feea382a49047"
    )
    assert core.ntfsfind(destination, path="/") == core.ntfsfind(ntfs_sample, path="/")
    with pytest.raises(NtfsDumpError, match="already exists"):
        core.ntfsfind(ntfs_sample, out_mft=str(ntfs_sample))
    assert ntfs_sample.stat().st_size == original_size


def test_real_cli_search(ntfs_sample):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ntfsfind",
            str(ntfs_sample),
            "^/test_dir/file_1.txt$",
            "--output-format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    record = json.loads(result.stdout)
    assert record["path"] == "/test_dir/file_1.txt"
    assert record["size"] == 6


def test_real_cli_fractional_byte_size_boundaries(ntfs_sample, tmp_path):
    exported_mft = tmp_path / "fractional-size.mft"
    core.ntfsfind(ntfs_sample, out_mft=str(exported_mft))

    expected = {
        ">=6.1B": [],
        "<6.1B": ["/test_dir/file_1.txt"],
        "6.1B..7B": [],
        "=6.1B": [],
    }
    query = r"^/test_dir/file_1\.txt$"
    for source in (ntfs_sample, exported_mft):
        for size, expected_paths in expected.items():
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ntfsfind",
                    str(source),
                    query,
                    "--size",
                    size,
                    "--output-format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            records = [json.loads(line) for line in result.stdout.splitlines()]
            assert [record["path"] for record in records] == expected_paths


def test_real_cli_accepts_empty_regex_and_still_requires_a_query_or_action(
    ntfs_sample,
):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ntfsfind",
            str(ntfs_sample),
            "",
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(records) == 102
    assert records == [
        json.loads(line)
        for line in core.ntfsfind(ntfs_sample, search_query="", output_format="json")
    ]

    missing_query = subprocess.run(
        [sys.executable, "-m", "ntfsfind", str(ntfs_sample)],
        capture_output=True,
        text=True,
    )
    assert missing_query.returncode == 2
    assert missing_query.stdout == ""
    assert "the following arguments are required: search_query" in missing_query.stderr


def test_real_multiprocess_matches_single_process(ntfs_sample, monkeypatch):
    # Use the real executor and native MFT parser, with two actual child workers.
    # This catches serialization/start-method issues hidden by executor doubles.
    monkeypatch.setattr(
        core, "ProcessPoolExecutor", lambda: ProcessPoolExecutor(max_workers=2)
    )
    kwargs = dict(path="/test_dir", extension="txt", output_format="json")
    single = core.ntfsfind(ntfs_sample, **kwargs)
    parallel = core.ntfsfind(ntfs_sample, multiprocess=True, **kwargs)
    assert single
    assert parallel == single


def test_real_nonresident_ads_size_filter(ntfs_sample):
    records = [
        json.loads(line)
        for line in core.ntfsfind(
            ntfs_sample, ads_only=True, size="20312", output_format="json"
        )
    ]
    assert [record["path"] for record in records] == ["/$Extend/$UsnJrnl:$J"]
    assert records[0]["size"] == 20312
    assert "/$Secure:$SDS" in core.ntfsfind(ntfs_sample, ads_only=True, size="264568")


def test_raw_attribute_id_scan_tolerates_unrelated_bad_fixup(ntfs_sample):
    mft = core.read_image_mft(ntfs_sample, core.ImageFile)
    record_size = int.from_bytes(mft[28:32], "little")
    damaged = bytearray(mft)
    # Corrupt an unrelated FILE record's USA trailer. The native parser keeps
    # searching the other records, so raw-ID enrichment must do the same.
    damaged[55 * record_size + 510] ^= 1

    with pytest.warns(UserWarning, match="fixup bytes are not equal"):
        matches = core.find_records(
            bytes(damaged), re.compile(r"^/test_dir/file_1\.txt$"), False
        )
    assert matches == ["/test_dir/file_1.txt"]


def test_real_mft_cloud_attribute_names_and_filters(ntfs_sample, tmp_path):
    mft = core.read_image_mft(ntfs_sample, core.ImageFile)
    record_size = int.from_bytes(mft[28:32], "little")
    record_start = 52 * record_size
    record = mft[record_start : record_start + record_size]

    # Locate the resident $STANDARD_INFORMATION value in record 52 and find
    # its flags field. This preserves the rest of the FILE record and its USA.
    attribute_offset = int.from_bytes(record[20:22], "little")
    flags_offset = None
    while attribute_offset + 16 <= len(record):
        attribute_type = int.from_bytes(
            record[attribute_offset : attribute_offset + 4], "little"
        )
        if attribute_type == 0xFFFFFFFF:
            break
        attribute_length = int.from_bytes(
            record[attribute_offset + 4 : attribute_offset + 8], "little"
        )
        if attribute_type == 0x10:
            assert record[attribute_offset + 8] == 0  # resident attribute
            value_offset = int.from_bytes(
                record[attribute_offset + 20 : attribute_offset + 22], "little"
            )
            flags_offset = record_start + attribute_offset + value_offset + 32
            break
        assert attribute_length >= 16
        attribute_offset += attribute_length

    assert flags_offset is not None
    assert int.from_bytes(mft[flags_offset : flags_offset + 4], "little") == 0x20

    cases = (
        (0x80000, "pinned", "FILE_ATTRIBUTE_PINNED"),
        (0x100000, "unpinned", "FILE_ATTRIBUTE_UNPINNED"),
        (0x400000, "recall_on_data_access", "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS"),
    )
    for bit, filter_name, json_name in cases:
        modified = bytearray(mft)
        modified[flags_offset : flags_offset + 4] = (0x20 | bit).to_bytes(4, "little")
        modified_path = tmp_path / f"record-52-{filter_name}.mft"
        modified_path.write_bytes(modified)

        query = r"^/test_dir/file_1\.txt$"
        json_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ntfsfind",
                str(modified_path),
                query,
                "--output-format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        record_json = json.loads(json_result.stdout)
        assert record_json["entry_id"] == 52
        assert record_json["file_flags"] == ["FILE_ATTRIBUTE_ARCHIVE", json_name]

        for _, candidate, _ in cases:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ntfsfind",
                    str(modified_path),
                    query,
                    "--attributes",
                    f"FILE_ATTRIBUTE_{candidate.upper()}",
                    "--output-format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            matches = [line for line in result.stdout.splitlines() if line]
            assert bool(matches) == (candidate == filter_name)
