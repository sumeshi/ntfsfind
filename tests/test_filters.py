import pickle
from datetime import datetime, timezone

import pytest

from ntfsdump.errors import NtfsDumpError

from ntfsfind.filters import (
    AdsFilter,
    AllocationFilter,
    AttributeFilter,
    ExtensionFilter,
    PathPrefixFilter,
    SizeFilter,
    TimestampFilter,
    TypeFilter,
    build_filters,
    extension_of,
    normalize_attribute_names,
    normalize_extension,
    normalize_prefix,
)
from ntfsfind.record import Record

KB = 1024
MB = 1024**2


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def make_record(**overrides) -> Record:
    values = {
        "path": "/Windows/System32/foo.evtx",
        "base_path": "/Windows/System32/foo.evtx",
        "entry_id": 1,
        "allocated": True,
        "is_dir": False,
        "size": 1024,
        "si_created": utc(2024, 6, 1, 12, 0, 0),
        "si_modified": utc(2024, 6, 2, 12, 0, 0),
        "si_accessed": utc(2024, 6, 3, 12, 0, 0),
        "fn_created": utc(2023, 1, 1, 12, 0, 0),
        "fn_modified": utc(2023, 1, 2, 12, 0, 0),
        "fn_accessed": utc(2023, 1, 3, 12, 0, 0),
        "file_flags": ("FILE_ATTRIBUTE_HIDDEN",),
        "is_data_stream": False,
    }
    values.update(overrides)
    return Record(**values)


def test_extension_of():
    assert extension_of("/a/b/c.evtx") == "evtx"
    assert extension_of("/a/b/C.EVTX") == "evtx"
    assert extension_of("c.Evtx") == "evtx"
    assert extension_of("/a/b/c") == ""
    assert extension_of("/a/b.c.d") == "d"
    assert extension_of("/a/b/.gitignore") == "gitignore"
    assert extension_of("C:\\Windows\\foo.exe") == "exe"


def test_normalize_prefix():
    assert normalize_prefix("/Windows/System32") == "windows/system32"
    assert normalize_prefix("Windows\\System32\\") == "windows/system32"
    assert normalize_prefix("  //Windows/System32//  ") == "windows/system32"
    assert normalize_prefix("/") == ""


def test_normalize_extension():
    assert normalize_extension("evtx") == "evtx"
    assert normalize_extension(".EVTX") == "evtx"
    assert normalize_extension("  .Exe  ") == "exe"
    assert normalize_extension("") == ""


def test_normalize_attribute_names_variants():
    expected = frozenset({"FILE_ATTRIBUTE_HIDDEN"})
    assert normalize_attribute_names("hidden") == expected
    assert normalize_attribute_names("HIDDEN") == expected
    assert normalize_attribute_names("file_attribute_hidden") == expected
    assert normalize_attribute_names("FILE_ATTRIBUTE_HIDDEN") == expected
    assert normalize_attribute_names(" hidden ") == expected


def test_normalize_attribute_names_multiple_and_iterable():
    assert normalize_attribute_names("hidden,system") == frozenset(
        {"FILE_ATTRIBUTE_HIDDEN", "FILE_ATTRIBUTE_SYSTEM"}
    )
    assert normalize_attribute_names(["hidden", "system"]) == frozenset(
        {"FILE_ATTRIBUTE_HIDDEN", "FILE_ATTRIBUTE_SYSTEM"}
    )
    assert normalize_attribute_names(None) == frozenset()
    assert normalize_attribute_names("hidden,,system") == frozenset(
        {"FILE_ATTRIBUTE_HIDDEN", "FILE_ATTRIBUTE_SYSTEM"}
    )


def test_extension_filter_matches_and_case():
    predicate = ExtensionFilter(frozenset({"evtx", "exe"}))

    assert predicate(make_record()) is True
    assert predicate(make_record(path="/a/B.EVTX", base_path="/a/B.EVTX")) is True
    assert predicate(make_record(path="/a/b.txt", base_path="/a/b.txt")) is False


def test_extension_filter_uses_base_path_for_ads():
    record = make_record(path="/a/foo.evtx:hidden", base_path="/a/foo.evtx")
    predicate = ExtensionFilter(frozenset({"evtx"}))

    assert predicate(record) is True
    assert ExtensionFilter(frozenset({"hidden"}))(record) is False


def test_path_prefix_filter_boundary_and_case():
    predicate = PathPrefixFilter(normalize_prefix("/Windows/System32"))

    assert predicate(make_record()) is True
    assert predicate(make_record(base_path="/windows/system32/x.dll")) is True
    assert predicate(make_record(base_path="/Windows/System321/x.dll")) is False
    assert predicate(make_record(base_path="/Windows")) is False


def test_path_prefix_filter_backslash_normalization():
    predicate = PathPrefixFilter(normalize_prefix("Windows\\System32"))
    record = make_record(base_path="/Windows\\System32\\kernel32.dll")

    assert predicate(record) is True


def test_size_filter_delegates_to_predicate():
    predicate = SizeFilter(build_filters(size=">=1KB")[0].predicate)

    assert predicate(make_record(size=KB)) is True
    assert predicate(make_record(size=KB - 1)) is False
    assert predicate(make_record(size=None)) is False


def test_timestamp_filter_source_and_field():
    si = TimestampFilter(
        build_filters(created=">=2024-01-01")[0].predicate, "created", "si"
    )
    fn = TimestampFilter(
        build_filters(created=">=2024-01-01")[0].predicate, "created", "fn"
    )

    assert si(make_record()) is True
    assert fn(make_record()) is False


def test_allocation_filter():
    assert AllocationFilter("allocated")(make_record(allocated=True)) is True
    assert AllocationFilter("allocated")(make_record(allocated=False)) is False
    assert AllocationFilter("deleted")(make_record(allocated=False)) is True
    assert AllocationFilter("deleted")(make_record(allocated=True)) is False


def test_type_filter():
    assert TypeFilter("files")(make_record(is_dir=False)) is True
    assert TypeFilter("files")(make_record(is_dir=True)) is False
    assert TypeFilter("dirs")(make_record(is_dir=True)) is True
    assert TypeFilter("dirs")(make_record(is_dir=False)) is False


def test_ads_filter():
    assert AdsFilter("ads")(make_record(is_data_stream=True)) is True
    assert AdsFilter("ads")(make_record(is_data_stream=False)) is False
    assert AdsFilter("no-ads")(make_record(is_data_stream=False)) is True
    assert AdsFilter("no-ads")(make_record(is_data_stream=True)) is False


def test_attribute_filter_and_semantics():
    predicate = AttributeFilter(
        frozenset({"FILE_ATTRIBUTE_HIDDEN", "FILE_ATTRIBUTE_SYSTEM"})
    )

    assert predicate(make_record(file_flags=("FILE_ATTRIBUTE_HIDDEN",))) is False
    assert (
        predicate(
            make_record(file_flags=("FILE_ATTRIBUTE_HIDDEN", "FILE_ATTRIBUTE_SYSTEM"))
        )
        is True
    )
    assert predicate(make_record(file_flags=())) is False


def test_build_filters_empty_when_no_options():
    assert build_filters() == []
    assert build_filters(extension=",") == []
    assert build_filters(attributes=" , ") == []


def test_build_filters_order_and_types():
    filters = build_filters(
        extension="evtx",
        path="/Windows",
        size=">=1KB",
        created=">=2024-01-01",
        modified=">=2024-01-01",
        accessed=">=2024-01-01",
        allocated_only=True,
        deleted_only=True,
        files_only=True,
        dirs_only=True,
        ads_only=True,
        no_ads=True,
        attributes="hidden",
    )

    assert [type(f) for f in filters] == [
        ExtensionFilter,
        PathPrefixFilter,
        SizeFilter,
        TimestampFilter,
        TimestampFilter,
        TimestampFilter,
        AllocationFilter,
        AllocationFilter,
        TypeFilter,
        TypeFilter,
        AdsFilter,
        AdsFilter,
        AttributeFilter,
    ]


def test_build_filters_extension_comma_string_and_iterable():
    from_string = build_filters(extension="evtx,exe")
    from_iterable = build_filters(extension=["EVTX", ".exe"])
    from_tuple = build_filters(extension=("evtx", ".exe"))

    assert from_string[0].extensions == frozenset({"evtx", "exe"})
    assert from_iterable[0].extensions == frozenset({"evtx", "exe"})
    assert from_tuple[0].extensions == frozenset({"evtx", "exe"})


def test_build_filters_combines_with_and():
    filters = build_filters(
        extension="evtx",
        path="/Windows/System32",
        size=">=1KB",
        created=">=2024-01-01",
        allocated_only=True,
        files_only=True,
        no_ads=True,
        attributes="hidden",
    )

    matching = make_record()
    assert all(f(matching) for f in filters)

    assert not all(
        f(make_record(path="/a/f.exe", base_path="/a/f.exe")) for f in filters
    )
    assert not all(
        f(make_record(path="/a/f.evtx", base_path="/a/f.evtx")) for f in filters
    )
    assert not all(f(make_record(size=10)) for f in filters)
    assert not all(f(make_record(si_created=utc(2020, 1, 1))) for f in filters)
    assert not all(f(make_record(allocated=False)) for f in filters)
    assert not all(f(make_record(is_dir=True)) for f in filters)
    assert not all(f(make_record(is_data_stream=True)) for f in filters)
    assert not all(f(make_record(file_flags=())) for f in filters)


def test_isolation_records_differ_in_one_dimension():
    base = make_record()
    other = make_record(
        base_path="/Windows/System32/bar.txt", path="/Windows/System32/bar.txt"
    )

    extension = build_filters(extension="evtx")[0]
    assert extension(base) is True
    assert extension(other) is False

    size_ok = build_filters(size="=1024")[0]
    size_other = make_record(size=2048)
    assert size_ok(base) is True
    assert size_ok(size_other) is False


def test_build_filters_picklable_and_still_evaluate():
    record = make_record()
    for predicate in build_filters(
        extension="evtx",
        path="/Windows/System32",
        size=">=1KB",
        created=">=2024-01-01",
        modified=">=2024-01-01",
        accessed=">=2024-01-01",
        allocated_only=True,
        files_only=True,
        no_ads=True,
        attributes="hidden",
    ):
        restored = pickle.loads(pickle.dumps(predicate))
        assert restored == predicate
        assert restored(record) is True


def test_build_filters_pickled_keeps_mismatch():
    predicate = pickle.loads(pickle.dumps(build_filters(size=">=10MB")[0]))

    assert predicate(make_record(size=10 * MB)) is True
    assert predicate(make_record(size=1)) is False


def test_build_filters_invalid_size_raises():
    with pytest.raises(NtfsDumpError):
        build_filters(size="bogus")


def test_build_filters_invalid_timestamp_raises():
    with pytest.raises(NtfsDumpError):
        build_filters(created="not-a-date")
    with pytest.raises(NtfsDumpError):
        build_filters(modified="2025-13-01")
    with pytest.raises(NtfsDumpError):
        build_filters(accessed=">=nope")
