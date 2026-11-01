"""Unit tests for ntfsfind.record using hand-made fake MFT entries."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from ntfsdump.errors import NtfsDumpError

from ntfsfind.filters import SizeFilter
from ntfsfind.parsers import parse_size
from ntfsfind.record import Record, iter_records, normalize_path, parse_flag_tokens


class FakeAttribute:
    def __init__(
        self,
        type_code=None,
        type_name=None,
        name="",
        attribute_content=None,
        is_resident=True,
        data_size=0,
    ):
        self.type_code = type_code
        self.type_name = type_name
        self.name = name
        self.attribute_content = attribute_content
        self.is_resident = is_resident
        self.data_size = data_size


class FakeEntry:
    def __init__(self, full_path="", attributes=(), **fields):
        self.full_path = full_path
        self._attributes = list(attributes)
        for key, value in fields.items():
            setattr(self, key, value)

    def attributes(self):
        return self._attributes


def test_parse_flag_tokens_with_parentheses():
    assert parse_flag_tokens("EntryFlags(ALLOCATED | INDEX_PRESENT)") == (
        "ALLOCATED",
        "INDEX_PRESENT",
    )
    assert parse_flag_tokens(
        "EntryFlags(ALLOCATED | IS_EXTENSION | SPECIAL_INDEX_PRESENT)"
    ) == ("ALLOCATED", "IS_EXTENSION", "SPECIAL_INDEX_PRESENT")


def test_extension_of_base_record_zero_is_joined():
    encoded_name = "extension".encode("utf-16le")
    reference = bytearray((26 + len(encoded_name) + 7) // 8 * 8)
    reference[:4] = (128).to_bytes(4, "little")
    reference[4:6] = len(reference).to_bytes(2, "little")
    reference[6] = len("extension")
    reference[7] = 26
    reference[16:24] = (100 | 1 << 48).to_bytes(8, "little")
    reference[24:26] = (5).to_bytes(2, "little")
    reference[26 : 26 + len(encoded_name)] = encoded_name
    unnamed_reference = bytearray(32)
    unnamed_reference[:4] = (128).to_bytes(4, "little")
    unnamed_reference[4:6] = len(unnamed_reference).to_bytes(2, "little")
    unnamed_reference[16:24] = (100 | 1 << 48).to_bytes(8, "little")
    unnamed_reference[24:26] = (7).to_bytes(2, "little")
    attribute_list = FakeAttribute(type_code=32)
    attribute_list.raw_value = bytes(reference + unnamed_reference)
    base = FakeEntry(
        full_path="/$MFT",
        entry_id=0,
        sequence=3,
        base_entry_id=0,
        base_entry_sequence=0,
        attributes=[attribute_list],
    )
    extension = FakeEntry(
        entry_id=100,
        sequence=1,
        base_entry_id=0,
        base_entry_sequence=3,
        attributes=[
            FakeAttribute(
                type_code=128,
                type_name="DATA",
                name="extension",
                attribute_content=SimpleNamespace(data=b"stream"),
            ),
            FakeAttribute(
                type_code=128,
                type_name="DATA",
                attribute_content=SimpleNamespace(data=b"file size"),
            ),
        ],
    )

    records = list(iter_records([base, extension]))
    assert [record.path for record in records] == ["/$MFT", "/$MFT:extension"]
    assert records[0].size == len(b"file size")


def test_nonresident_attribute_list_joins_only_matching_raw_attribute_id():
    ref = bytearray(32)
    ref[:4] = (128).to_bytes(4, "little")
    ref[4:6] = len(ref).to_bytes(2, "little")
    ref[16:24] = (100 | 1 << 48).to_bytes(8, "little")
    ref[24:26] = (7).to_bytes(2, "little")
    attribute_list = FakeAttribute(type_code=32, is_resident=False)
    base = FakeEntry(
        full_path="/file",
        entry_id=50,
        sequence=3,
        base_entry_id=0,
        base_entry_sequence=0,
        attributes=[attribute_list],
    )
    extension = FakeEntry(
        entry_id=100,
        sequence=1,
        base_entry_id=50,
        base_entry_sequence=3,
        attributes=[
            FakeAttribute(
                type_code=128,
                name="",
                attribute_content=SimpleNamespace(data=b"joined"),
            )
        ],
    )
    raw_ids = {
        50: [((32, "", 0), 9)],
        100: [((128, "", 0), 7)],
    }
    values = {(50, 9): bytes(ref)}

    record = list(
        iter_records(
            [base, extension],
            attribute_list_values=values,
            raw_attribute_ids=raw_ids,
        )
    )[0]
    assert record.size == len(b"joined")

    wrong_id = {**raw_ids, 100: [((128, "", 0), 8)]}
    record = list(
        iter_records(
            [base, extension],
            attribute_list_values=values,
            raw_attribute_ids=wrong_id,
        )
    )[0]
    assert record.size is None

    duplicate_signature = {
        **raw_ids,
        100: [((128, "", 0), 7), ((128, "", 0), 8)],
    }
    record = list(
        iter_records(
            [base, extension],
            attribute_list_values=values,
            raw_attribute_ids=duplicate_signature,
        )
    )[0]
    assert record.size is None


def test_nonresident_attribute_list_without_image_value_fails_clearly():
    base = FakeEntry(
        full_path="/file",
        entry_id=50,
        sequence=3,
        base_entry_id=0,
        base_entry_sequence=0,
        attributes=[FakeAttribute(type_code=32, is_resident=False)],
    )
    with pytest.raises(NtfsDumpError, match="Search the original disk image"):
        list(iter_records([base]))


def test_parse_flag_tokens_without_parentheses():
    assert parse_flag_tokens("ALLOCATED | INDEX_PRESENT") == (
        "ALLOCATED",
        "INDEX_PRESENT",
    )


def test_parse_flag_tokens_none_and_empty():
    assert parse_flag_tokens(None) == ()
    assert parse_flag_tokens("") == ()
    assert parse_flag_tokens("(empty)") == ()


def test_numeric_binding_flags_take_precedence_over_display_strings():
    entry = FakeEntry(
        full_path="/directory",
        flags="display string is not an API",
        flags_value=3,
        attributes=[
            FakeAttribute(
                type_code=16,
                attribute_content=SimpleNamespace(
                    file_flags="(empty)", file_flags_value=0
                ),
            )
        ],
    )
    record = next(iter_records([entry]))
    assert record.allocated and record.is_dir
    assert record.file_flags == ()


def test_numeric_binding_flags_preserve_unknown_bits():
    entry = FakeEntry(
        full_path="/file",
        attributes=[
            FakeAttribute(
                type_code=16,
                attribute_content=SimpleNamespace(file_flags_value=0x80000006),
            )
        ],
    )
    assert next(iter_records([entry])).file_flags == (
        "FILE_ATTRIBUTE_HIDDEN",
        "FILE_ATTRIBUTE_SYSTEM",
        "0x80000000",
    )


def test_numeric_binding_file_attributes_use_windows_sdk_bit_values():
    entry = FakeEntry(
        full_path="/file",
        attributes=[
            FakeAttribute(
                type_code=16,
                attribute_content=SimpleNamespace(
                    file_flags_value=0x80800000 | 0x80000 | 0x100000 | 0x400000
                ),
            )
        ],
    )

    assert next(iter_records([entry])).file_flags == (
        "FILE_ATTRIBUTE_PINNED",
        "FILE_ATTRIBUTE_UNPINNED",
        "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS",
        "0x80800000",
    )


def test_raw_numeric_file_attribute_flags_use_windows_sdk_bit_values():
    assert parse_flag_tokens(
        "FileAttributeFlags(0x80000 | 0x100000 | 0x400000 | 0x80000000)"
    ) == (
        "FILE_ATTRIBUTE_PINNED",
        "FILE_ATTRIBUTE_UNPINNED",
        "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS",
        "0x80000000",
    )


def test_parse_flag_tokens_tuple_input():
    assert parse_flag_tokens(("ALLOCATED", "INDEX_PRESENT")) == (
        "ALLOCATED",
        "INDEX_PRESENT",
    )
    assert parse_flag_tokens(("ALLOCATED", "")) == ("ALLOCATED",)


def test_parse_flag_tokens_numeric_zero_is_dropped():
    assert parse_flag_tokens("FileAttributeFlags(0x0)") == ()
    assert parse_flag_tokens("EntryFlags(0x0)") == ()


def test_parse_flag_tokens_numeric_bits_are_expanded():
    assert parse_flag_tokens("FileAttributeFlags(0x3)") == (
        "FILE_ATTRIBUTE_READONLY",
        "FILE_ATTRIBUTE_HIDDEN",
    )
    assert parse_flag_tokens("EntryFlags(0x3)") == (
        "ALLOCATED",
        "INDEX_PRESENT",
    )
    assert parse_flag_tokens("FileAttributeFlags(0x1 | 0x40000000)") == (
        "FILE_ATTRIBUTE_READONLY",
        "0x40000000",
    )


def test_normalize_path_windows_separators():
    assert normalize_path(r"Windows\System32\cmd.exe") == "/Windows/System32/cmd.exe"


def test_normalize_path_keeps_existing_leading_slash():
    assert normalize_path("/Windows/System32/cmd.exe") == "/Windows/System32/cmd.exe"


def test_normalize_path_dot_and_unknown():
    assert normalize_path(".") == "/."
    assert normalize_path("[UNKNOWN]") == "/[UNKNOWN]"


def test_iter_records_yields_base_then_named_attributes_in_order():
    attributes = [
        FakeAttribute(type_code=128, type_name="DATA", name=""),
        FakeAttribute(type_code=128, type_name="DATA", name="Zone.Identifier"),
        FakeAttribute(type_code=144, type_name="IndexRoot", name="$I30"),
        FakeAttribute(type_code=128, type_name="DATA", name="Zone.Identifier"),
    ]
    entry = FakeEntry(
        full_path=r"Windows\a.txt",
        flags="EntryFlags(ALLOCATED)",
        attributes=attributes,
    )

    records = list(iter_records([entry]))

    assert [record.path for record in records] == [
        "/Windows/a.txt",
        "/Windows/a.txt:Zone.Identifier",
        "/Windows/a.txt:$I30",
        "/Windows/a.txt:Zone.Identifier",
    ]
    assert records[0].stream_name is None
    assert records[0].is_data_stream is False


def test_iter_records_stream_metadata_and_data_stream_flag():
    attributes = [
        FakeAttribute(
            type_code=128,
            type_name="DATA",
            name="Zone.Identifier",
            attribute_content=SimpleNamespace(data=b"x" * 55),
        ),
        FakeAttribute(
            type_code=144,
            type_name="IndexRoot",
            name="$I30",
            attribute_content=SimpleNamespace(data=b"x" * 66),
        ),
    ]
    entry = FakeEntry(
        full_path="/a.txt",
        flags="EntryFlags(ALLOCATED)",
        entry_id=7,
        file_size=123,
        attributes=attributes,
    )

    base, data_record, index_record = list(iter_records([entry]))

    assert data_record.stream_name == "Zone.Identifier"
    assert data_record.is_data_stream is True
    assert index_record.stream_name == "$I30"
    assert index_record.is_data_stream is False
    assert data_record.base_path == "/a.txt"
    assert index_record.base_path == "/a.txt"
    assert data_record.entry_id == 7
    assert data_record.size == 55
    assert index_record.size == 66
    assert base.size == 123
    assert base.ads == ("Zone.Identifier",)


def test_iter_records_stream_size_is_none_without_size_metadata():
    # Without resident bytes or readable non-resident size metadata, report
    # None instead of borrowing the base file's size.
    attributes = [
        FakeAttribute(type_code=128, type_name="DATA", name="Zone.Identifier"),
        FakeAttribute(type_code=144, type_name="IndexRoot", name="$I30"),
    ]
    entry = FakeEntry(full_path="/a.txt", file_size=123, attributes=attributes)

    data_record, index_record = list(iter_records([entry]))[1:]

    assert data_record.size is None
    assert index_record.size is None


def test_iter_records_stream_size_ignores_attribute_data_size():
    # attribute.data_size is the MFT attribute record length (e.g. $MFT's
    # $DATA reports 72 while the real file is 262144 bytes): never a size.
    attributes = [
        FakeAttribute(
            type_code=128,
            type_name="DATA",
            name="Zone.Identifier",
            data_size=72,
            attribute_content=None,
        ),
    ]
    entry = FakeEntry(full_path="/a.txt", file_size=262144, attributes=attributes)

    base, data_record = list(iter_records([entry]))

    assert base.size == 262144
    assert data_record.size is None


@pytest.mark.parametrize("first_vcn, expected", [(0, 20312), (8, None), (None, None)])
def test_nonresident_stream_size_is_valid_only_in_first_extent(first_vcn, expected):
    attribute = FakeAttribute(
        type_code=128,
        name="stream",
        is_resident=False,
        attribute_content=SimpleNamespace(vcn_first=first_vcn, file_size=20312),
    )
    entry = FakeEntry(full_path="/a", file_size=999, attributes=[attribute])
    record = list(iter_records([entry]))[1]
    assert record.size == expected
    assert SizeFilter(parse_size(">=1B"))(record) is (expected is not None)


def test_iter_records_data_like_type_name_with_other_type_code_is_not_data_stream():
    attributes = [
        FakeAttribute(type_code=144, type_name="DATA", name="weird"),
    ]
    entry = FakeEntry(full_path="/a", attributes=attributes)

    base, stream_record = list(iter_records([entry]))

    assert base.ads == ()
    assert stream_record.stream_name == "weird"
    assert stream_record.is_data_stream is False


def test_iter_records_ads_contains_only_named_data_attributes():
    attributes = [
        FakeAttribute(type_code=128, type_name="DATA", name=""),
        FakeAttribute(type_code=128, type_name="DATA", name="a"),
        FakeAttribute(type_code=128, type_name="DATA", name="a"),
        FakeAttribute(type_code=144, type_name="IndexRoot", name="$I30"),
    ]
    entry = FakeEntry(full_path="/a", attributes=attributes)

    record = list(iter_records([entry]))[0]

    assert record.ads == ("a", "a")


def test_iter_records_allocated_and_directory_flags():
    def base_record(flags):
        entry = FakeEntry(full_path="/a", flags=flags)
        return list(iter_records([entry]))[0]

    assert base_record("EntryFlags(ALLOCATED)").allocated is True
    assert base_record("EntryFlags(ALLOCATED)").is_dir is False
    assert base_record("EntryFlags(INDEX_PRESENT)").allocated is False
    assert base_record("EntryFlags(INDEX_PRESENT)").is_dir is True
    assert base_record("EntryFlags(ALLOCATED | INDEX_PRESENT)").is_dir is True
    assert base_record("EntryFlags(SPECIAL_INDEX_PRESENT)").is_dir is True
    assert base_record("EntryFlags(IS_EXTENSION)").allocated is False
    assert base_record("EntryFlags(IS_EXTENSION)").is_dir is False
    assert base_record(None).allocated is False
    assert base_record(None).is_dir is False


def test_iter_records_size_prefers_entry_file_size_over_fn_logical_size():
    si = SimpleNamespace(created=None)
    attributes = [
        FakeAttribute(
            type_code=16, type_name="StandardInformation", attribute_content=si
        ),
        FakeAttribute(
            type_code=48,
            type_name="FileName",
            attribute_content=SimpleNamespace(logical_size=111),
        ),
        FakeAttribute(
            type_code=48,
            type_name="FileName",
            attribute_content=SimpleNamespace(logical_size=222),
        ),
        # attribute data_size values (333/444) are MFT record lengths and
        # must be ignored as size sources.
        FakeAttribute(type_code=128, type_name="DATA", name="", data_size=333),
        FakeAttribute(type_code=128, type_name="DATA", name="ads", data_size=444),
    ]
    entry = FakeEntry(
        full_path="/a",
        flags="EntryFlags(ALLOCATED)",
        file_size=999,
        attributes=attributes,
    )

    record = list(iter_records([entry]))[0]

    assert record.size == 999


def test_iter_records_size_falls_back_to_fn_logical_size():
    attributes = [
        FakeAttribute(
            type_code=48,
            type_name="FileName",
            attribute_content=SimpleNamespace(logical_size=111),
        ),
    ]
    entry = FakeEntry(
        full_path="/a",
        flags="EntryFlags(INDEX_PRESENT)",
        file_size=None,
        attributes=attributes,
    )

    assert list(iter_records([entry]))[0].size == 111


def test_iter_records_size_falls_back_to_file_size_without_fn():
    attributes = [
        FakeAttribute(type_code=128, type_name="DATA", name=""),
    ]
    entry = FakeEntry(full_path="/a", file_size=999, attributes=attributes)

    assert list(iter_records([entry]))[0].size == 999


def test_iter_records_size_falls_back_to_entry_file_size():
    fn = SimpleNamespace(logical_size=None)
    attributes = [
        FakeAttribute(type_code=48, type_name="FileName", attribute_content=fn)
    ]
    entry = FakeEntry(full_path="/a", file_size=999, attributes=attributes)

    assert list(iter_records([entry]))[0].size == 999


def test_iter_records_size_none_without_fn_or_file_size():
    entry = FakeEntry(full_path="/a")

    assert list(iter_records([entry]))[0].size is None


def test_iter_records_maps_si_and_fn_timestamps_and_flags():
    si_created = datetime(2024, 1, 1, 1, 2, 3, tzinfo=timezone.utc)
    si_modified = datetime(2024, 1, 2, 1, 2, 3, tzinfo=timezone.utc)
    si_accessed = datetime(2024, 1, 3, 1, 2, 3, tzinfo=timezone.utc)
    si_mft_modified = datetime(2024, 1, 4, 1, 2, 3, tzinfo=timezone.utc)
    fn_created = datetime(2025, 2, 1, 1, 2, 3, tzinfo=timezone.utc)
    fn_modified = datetime(2025, 2, 2, 1, 2, 3, tzinfo=timezone.utc)
    fn_accessed = datetime(2025, 2, 3, 1, 2, 3, tzinfo=timezone.utc)
    fn_mft_modified = datetime(2025, 2, 4, 1, 2, 3, tzinfo=timezone.utc)

    si = SimpleNamespace(
        created=si_created,
        modified=si_modified,
        accessed=si_accessed,
        mft_modified=si_mft_modified,
        file_flags=(
            "FileAttributeFlags(FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)"
        ),
    )
    fn = SimpleNamespace(
        created=fn_created,
        modified=fn_modified,
        accessed=fn_accessed,
        mft_modified=fn_mft_modified,
        logical_size=10,
        flags="FileAttributeFlags(FILE_ATTRIBUTE_READONLY)",
    )
    attributes = [
        FakeAttribute(type_name="StandardInformation", attribute_content=si),
        FakeAttribute(type_code=48, type_name="FileName", attribute_content=fn),
    ]
    entry = FakeEntry(full_path="/a", attributes=attributes)

    record = list(iter_records([entry]))[0]

    assert record.si_created == si_created
    assert record.si_modified == si_modified
    assert record.si_accessed == si_accessed
    assert record.si_mft_modified == si_mft_modified
    assert record.fn_created == fn_created
    assert record.fn_modified == fn_modified
    assert record.fn_accessed == fn_accessed
    assert record.fn_mft_modified == fn_mft_modified
    assert record.file_flags == (
        "FILE_ATTRIBUTE_HIDDEN",
        "FILE_ATTRIBUTE_SYSTEM",
    )


def test_iter_records_file_flags_falls_back_to_fn():
    fn = SimpleNamespace(
        logical_size=1,
        flags="FileAttributeFlags(FILE_ATTRIBUTE_READONLY)",
    )
    attributes = [
        FakeAttribute(type_code=48, type_name="FileName", attribute_content=fn)
    ]
    entry = FakeEntry(full_path="/a", attributes=attributes)

    assert list(iter_records([entry]))[0].file_flags == ("FILE_ATTRIBUTE_READONLY",)


def test_iter_records_file_flags_empty_without_si_or_fn():
    entry = FakeEntry(full_path="/a")

    assert list(iter_records([entry]))[0].file_flags == ()


def test_iter_records_entry_id_and_hard_link_count_defaults():
    entry = FakeEntry(full_path="/a")

    record = list(iter_records([entry]))[0]

    assert record.entry_id == 0
    assert record.hard_link_count == 0


def test_missing_parent_does_not_reuse_unrelated_parser_path():
    filename = SimpleNamespace(
        name="orphan.txt",
        parent_entry_id=777,
        parent_entry_sequence=1,
        namespace="POSIX",
    )
    entry = FakeEntry(
        full_path="/unrelated/orphan.txt",
        entry_id=52,
        sequence=1,
        attributes=[FakeAttribute(type_code=48, attribute_content=filename)],
    )

    assert [record.path for record in iter_records([entry])] == [
        "/[UNKNOWN]/orphan.txt"
    ]


def test_iter_records_entry_id_and_hard_link_count_values():
    entry = FakeEntry(full_path="/a", entry_id=42, hard_link_count=3)

    record = list(iter_records([entry]))[0]

    assert record.entry_id == 42
    assert record.hard_link_count == 3


def test_stream_timestamp_selects_source():
    created = datetime(2024, 5, 6, 7, 8, 9, tzinfo=timezone.utc)
    modified = datetime(2024, 5, 7, 7, 8, 9, tzinfo=timezone.utc)
    record = Record(
        path="/a.txt",
        base_path="/a.txt",
        entry_id=1,
        allocated=True,
        is_dir=False,
        size=0,
        si_created=created,
        si_modified=modified,
    )

    assert record.stream_timestamp("si") == (created, modified)
    assert record.stream_timestamp("fn") == (None, None)


def test_size_filter_applies_to_stream_own_size():
    attributes = [
        FakeAttribute(type_code=128, type_name="DATA", name=""),
        FakeAttribute(
            type_code=128,
            type_name="DATA",
            name="ads",
            attribute_content=SimpleNamespace(data=b"x" * 50),
        ),
    ]
    entry = FakeEntry(full_path="/a", file_size=1000, attributes=attributes)
    base, stream_record = list(iter_records([entry]))

    keep_large = SizeFilter(parse_size(">=500"))

    assert base.size == 1000
    assert stream_record.size == 50
    assert keep_large(base) is True
    assert keep_large(stream_record) is False


def test_size_filter_excludes_streams_of_unknown_size():
    # Streams with missing size metadata must not match a size filter or
    # inherit the base file's size.
    attributes = [
        FakeAttribute(type_code=128, type_name="DATA", name=""),
        FakeAttribute(type_code=128, type_name="DATA", name="ads"),
    ]
    entry = FakeEntry(full_path="/a", file_size=1000, attributes=attributes)
    base, stream_record = list(iter_records([entry]))

    keep_small = SizeFilter(parse_size("<=500"))

    assert stream_record.size is None
    assert keep_small(base) is False
    assert keep_small(stream_record) is False
