import json
import pickle
import re

import pytest
from ntfsdump.errors import NtfsDumpError
from ntfsdump.image import is_ntfs_volume_description

from ntfsfind import core
from ntfsfind import filters as filters_module
from ntfsfind.record import Record, iter_records


class FakeAttribute:
    def __init__(self, name):
        self.name = name


class FakeEntry:
    def __init__(self, full_path, attributes=()):
        self.full_path = full_path
        self._attributes = list(attributes)

    def attributes(self):
        return self._attributes


def test_is_mft_file_accepts_file_and_baad(tmp_path):
    valid = tmp_path / "valid.mft"
    valid.write_bytes(b"FILE" + b"\x00" * 64)
    baad = tmp_path / "baad.mft"
    baad.write_bytes(b"BAAD" + b"\x00" * 64)

    assert core.is_mft_file(str(valid)) is True
    assert core.is_mft_file(str(baad)) is True


def test_is_mft_file_rejects_other_inputs(tmp_path):
    other = tmp_path / "other.bin"
    other.write_bytes(b"\x00" * 64)

    assert core.is_mft_file(str(other)) is False
    assert core.is_mft_file(str(tmp_path)) is False
    assert core.is_mft_file(str(tmp_path / "missing.bin")) is False


def test_gen_filepaths_normalizes_windows_paths():
    entries = [
        FakeEntry(
            r"Windows\System32\cmd.exe",
            [FakeAttribute(None), FakeAttribute("Zone.Identifier")],
        )
    ]

    assert list(core.gen_filepaths(entries)) == [
        "/Windows/System32/cmd.exe",
        "/Windows/System32/cmd.exe:Zone.Identifier",
    ]


def test_gen_filepaths_does_not_double_prefix():
    entries = [FakeEntry("/Windows/System32/cmd.exe")]

    assert list(core.gen_filepaths(entries)) == ["/Windows/System32/cmd.exe"]


def test_filter_by_pattern_matches_and_misses():
    pattern = re.compile(r"\.evtx$")

    assert core.filter_by_pattern(pattern, "/Logs/Setup.evtx") == "/Logs/Setup.evtx"
    assert core.filter_by_pattern(pattern, "/Logs/Setup.log") is None


def test_filter_by_pattern_uses_search_semantics():
    pattern = re.compile(r"Setup")

    assert core.filter_by_pattern(pattern, "/Logs/Setup.evtx") == "/Logs/Setup.evtx"


def test_ntfsfind_fixed_strings_escapes_dot(tmp_path, monkeypatch):
    source = tmp_path / "evidence.mft"
    source.write_bytes(b"FILE" + b"\x00" * 64)
    captured = {}

    def fake_find_records(mft, pattern, multiprocess):
        captured["pattern"] = pattern
        return []

    monkeypatch.setattr(core, "is_mft_file", lambda path: True)
    monkeypatch.setattr(core, "find_records", fake_find_records)

    result = core.ntfsfind(source=str(source), search_query="a.b", fixed_strings=True)

    assert result == []
    assert captured["pattern"].pattern == re.escape("a.b")


def test_ntfsfind_ignore_case_sets_flag(tmp_path, monkeypatch):
    source = tmp_path / "evidence.mft"
    source.write_bytes(b"FILE" + b"\x00" * 64)
    captured = {}

    def fake_find_records(mft, pattern, multiprocess):
        captured["pattern"] = pattern
        return []

    monkeypatch.setattr(core, "is_mft_file", lambda path: True)
    monkeypatch.setattr(core, "find_records", fake_find_records)

    result = core.ntfsfind(source=str(source), search_query="ABC", ignore_case=True)

    assert result == []
    assert captured["pattern"].flags & re.IGNORECASE


def test_ntfsfind_skips_search_without_query(tmp_path, monkeypatch):
    source = tmp_path / "evidence.mft"
    source.write_bytes(b"FILE" + b"\x00" * 64)

    def fail_find_records(mft, pattern, multiprocess):
        raise AssertionError("find_records must not be called")

    monkeypatch.setattr(core, "is_mft_file", lambda path: True)
    monkeypatch.setattr(core, "find_records", fail_find_records)

    assert core.ntfsfind(source=str(source)) == []


def test_gpt_volume_description_detection():
    # GPT desc判定 is provided by ntfsdump 3.2.0 (is_ntfs_volume_description).
    assert is_ntfs_volume_description("NTFS / exFAT (0x07)") is True
    assert is_ntfs_volume_description("Basic data partition") is True
    assert is_ntfs_volume_description("Windows Recovery Environment") is True
    assert is_ntfs_volume_description("EFI system partition") is False
    assert is_ntfs_volume_description("Unallocated") is False


def _make_fake_parser(entries):
    class FakeParser:
        def __init__(self, stream):
            self._entries = entries

        def entries(self):
            return self._entries

    return FakeParser


class FakeExecutorRecorder:
    last_chunksize = None
    last_max_workers = None

    def __init__(self, max_workers=None):
        FakeExecutorRecorder.last_max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def map(self, func, iterable, chunksize=1):
        FakeExecutorRecorder.last_chunksize = chunksize
        return map(func, iterable)


def test_find_records_applies_filters_single(monkeypatch):
    entries = [FakeEntry(r"a\b\c.exe"), FakeEntry(r"a\b\d.txt")]
    monkeypatch.setattr(core, "PyMftParser", _make_fake_parser(entries))
    filters = filters_module.build_filters(extension="exe")

    assert core.find_records(b"", None, False, filters=filters) == ["/a/b/c.exe"]


def test_find_records_multiprocess_matches_single(monkeypatch):
    entries = [
        FakeEntry(r"a\b\c.exe"),
        FakeEntry(r"a\b\d.txt"),
        FakeEntry(r"x\y\z.exe"),
    ]
    monkeypatch.setattr(core, "PyMftParser", _make_fake_parser(entries))
    monkeypatch.setattr(core, "ProcessPoolExecutor", FakeExecutorRecorder)

    filters = filters_module.build_filters(extension="exe")
    single = core.find_records(b"", None, False, filters=filters)
    multi = core.find_records(b"", None, True, filters=filters)

    assert single == ["/a/b/c.exe", "/x/y/z.exe"]
    assert multi == single
    assert FakeExecutorRecorder.last_chunksize == 10000


def test_find_records_output_format_routing(monkeypatch):
    entries = [FakeEntry(r"a\b\c.exe")]
    monkeypatch.setattr(core, "PyMftParser", _make_fake_parser(entries))

    json_lines = core.find_records(b"", None, False, output_format="json")
    assert len(json_lines) == 1
    payload = json.loads(json_lines[0])
    assert payload["path"] == "/a/b/c.exe"
    assert payload["entry_id"] == 0

    csv_lines = core.find_records(b"", None, False, output_format="csv")
    assert csv_lines[0].startswith("path,")
    assert "/a/b/c.exe" in csv_lines[1]

    table_lines = core.find_records(b"", None, False, output_format="table")
    assert table_lines[0].split()[0] == "ENTRY"


def test_records_and_filters_are_picklable():
    entries = [FakeEntry(r"a\b\c.exe", [FakeAttribute("Zone.Identifier")])]
    records = list(iter_records(entries))
    restored = pickle.loads(pickle.dumps(records))
    assert [record.path for record in restored] == [record.path for record in records]

    filters = filters_module.build_filters(
        extension="exe", size=">=1", allocated_only=True
    )
    restored_filters = pickle.loads(pickle.dumps(filters))
    record = Record(
        path="/a/b/c.exe",
        base_path="/a/b/c.exe",
        entry_id=1,
        allocated=True,
        is_dir=False,
        size=10,
    )
    assert all(predicate(record) for predicate in restored_filters)


def test_ntfsfind_validates_filters_before_io():
    with pytest.raises(NtfsDumpError) as excinfo:
        core.ntfsfind(source="/nonexistent/evidence.raw", size="bogus")
    assert "size" in str(excinfo.value).lower()


def test_ntfsfind_filter_only_uses_full_call(tmp_path, monkeypatch):
    source = tmp_path / "evidence.mft"
    source.write_bytes(b"FILE" + b"\x00" * 64)
    captured = {}

    def fake_find_records(
        mft, pattern, multiprocess, filters, output_format, timestamp_source
    ):
        captured["pattern"] = pattern
        captured["filters"] = filters
        captured["output_format"] = output_format
        return ["/a/b/c.evtx"]

    monkeypatch.setattr(core, "is_mft_file", lambda path: True)
    monkeypatch.setattr(core, "find_records", fake_find_records)

    result = core.ntfsfind(source=str(source), extension="evtx")

    assert result == ["/a/b/c.evtx"]
    assert captured["pattern"] is None
    assert captured["filters"]
    assert captured["output_format"] == "text"


def test_find_records_combines_pattern_and_filters(monkeypatch):
    entries = [
        FakeEntry(r"a\b\c.exe"),
        FakeEntry(r"a\b\c.txt"),
        FakeEntry(r"x\y\c.exe"),
    ]
    monkeypatch.setattr(core, "PyMftParser", _make_fake_parser(entries))
    filters = filters_module.build_filters(extension="exe")
    pattern = re.compile(r"c\.exe$")

    assert core.find_records(b"", pattern, False, filters=filters) == [
        "/a/b/c.exe",
        "/x/y/c.exe",
    ]
