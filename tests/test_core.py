import re

from ntfsdump.image import is_ntfs_volume_description

from ntfsfind import core


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
