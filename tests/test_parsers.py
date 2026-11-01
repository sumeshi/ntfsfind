from datetime import datetime, timezone
import pickle

import pytest

from ntfsdump.errors import NtfsDumpError

from ntfsfind.parsers import SizePredicate, TimePredicate, parse_size, parse_time

KB = 1024
MB = 1024**2
GB = 1024**3


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_parse_size_greater_equal():
    predicate = parse_size(">=10MB")

    assert predicate == SizePredicate(lower=10 * MB, lower_inclusive=True)
    assert predicate.upper is None


def test_parse_size_less_than():
    predicate = parse_size("<1KB")

    assert predicate == SizePredicate(upper=KB, upper_inclusive=False)
    assert predicate.lower is None


def test_parse_size_range():
    predicate = parse_size("4KB..10MB")

    assert predicate == SizePredicate(
        lower=4 * KB,
        lower_inclusive=True,
        upper=10 * MB,
        upper_inclusive=True,
    )


def test_parse_size_bare_value_is_equality():
    predicate = parse_size("100")

    assert predicate.lower == 100
    assert predicate.upper == 100
    assert predicate.lower_inclusive is True
    assert predicate.upper_inclusive is True


def test_parse_size_equals_operator():
    predicate = parse_size("=0")

    assert predicate.lower == 0
    assert predicate.upper == 0
    assert predicate(0) is True
    assert predicate(1) is False


def test_parse_size_unitless_is_bytes():
    assert parse_size("512").lower == 512


def test_parse_size_decimal_integral_values_are_unchanged():
    assert parse_size("1.5MB").lower == 3 * MB // 2
    assert parse_size("1.5KB").lower == 3 * KB // 2


def test_parse_size_fractional_byte_thresholds_are_exact():
    assert parse_size(">=0.1KB")(102) is False
    assert parse_size(">=0.1KB")(103) is True
    assert parse_size(">=6.1B")(6) is False
    assert parse_size("<=0.1KB")(102) is True
    assert parse_size("<=0.1KB")(103) is False
    assert parse_size(">0.1B")(0) is False
    assert parse_size(">0.1B")(1) is True
    assert parse_size("<0.1B")(0) is True
    assert parse_size("<0.1B")(1) is False


def test_parse_size_fractional_ranges_and_equality_are_exact():
    predicate = parse_size("0.1KB..0.2KB")
    assert predicate(102) is False
    assert predicate(103) is True
    assert predicate(204) is True
    assert predicate(205) is False

    # No integer byte count is exactly 0.1KB, so exact equality matches none.
    equality = parse_size("=0.1KB")
    assert equality(102) is False
    assert equality(103) is False
    assert parse_size("=0.0B")(0) is True


def test_fractional_size_predicate_is_pickleable():
    predicate = parse_size(">=0.1KB")
    restored = pickle.loads(pickle.dumps(predicate))
    assert restored == predicate
    assert restored(102) is False
    assert restored(103) is True


def test_parse_size_units_are_case_insensitive():
    assert parse_size(">=2gb").lower == 2 * GB


def test_parse_size_empty_range_ends():
    lower = parse_size("..1KB")
    assert lower.lower is None
    assert lower.upper == KB

    upper = parse_size("1KB..")
    assert upper.lower == KB
    assert upper.upper is None


@pytest.mark.parametrize("spec", ["", "   ", "abc", "10XB", "-5KB", ">=abc", "1.2.3MB"])
def test_parse_size_invalid_raises(spec):
    with pytest.raises(NtfsDumpError):
        parse_size(spec)


def test_size_predicate_comparison_operators():
    assert parse_size(">=10MB")(10 * MB) is True
    assert parse_size(">=10MB")(10 * MB - 1) is False

    assert parse_size(">10MB")(10 * MB) is False
    assert parse_size(">10MB")(10 * MB + 1) is True

    assert parse_size("<=10MB")(10 * MB) is True
    assert parse_size("<=10MB")(10 * MB + 1) is False

    assert parse_size("<10MB")(10 * MB) is False
    assert parse_size("<10MB")(10 * MB - 1) is True


def test_size_predicate_range_boundaries():
    predicate = parse_size("4KB..10MB")

    assert predicate(4 * KB) is True
    assert predicate(4 * KB - 1) is False
    assert predicate(10 * MB) is True
    assert predicate(10 * MB + 1) is False
    assert predicate(7 * MB) is True


def test_size_predicate_none_is_false():
    assert parse_size(">=1").matches(None) is False
    assert SizePredicate(lower=0)(None) is False


def test_size_predicate_matches_equals_call():
    predicate = parse_size("4KB..10MB")

    assert predicate.matches(5 * MB) is predicate(5 * MB)


def test_parse_time_range_whole_days():
    predicate = parse_time("2024-01-01..2024-12-31")

    assert predicate.start == utc(2024, 1, 1, 0, 0, 0)
    assert predicate.start_inclusive is True
    assert predicate.end == utc(2024, 12, 31, 23, 59, 59, 999999)
    assert predicate.end_inclusive is True

    assert predicate(utc(2024, 1, 1, 0, 0, 0)) is True
    assert predicate(utc(2024, 7, 1, 12, 0, 0)) is True
    assert predicate(utc(2024, 12, 31, 23, 59, 59, 999999)) is True
    assert predicate(utc(2023, 12, 31, 23, 59, 59, 999999)) is False
    assert predicate(utc(2025, 1, 1, 0, 0, 0)) is False


def test_parse_time_greater_equal_date():
    predicate = parse_time(">=2025-04-01")

    assert predicate.start == utc(2025, 4, 1, 0, 0, 0)
    assert predicate.start_inclusive is True
    assert predicate.end is None

    assert predicate(utc(2025, 3, 31, 23, 59, 59, 999999)) is False
    assert predicate(utc(2025, 4, 1, 0, 0, 0)) is True


def test_parse_time_datetime_open_range():
    predicate = parse_time("2025-04-01T09:00..")

    assert predicate.start == utc(2025, 4, 1, 9, 0, 0)
    assert predicate.start_inclusive is True
    assert predicate.end is None
    assert predicate(utc(2025, 4, 1, 8, 59, 59)) is False
    assert predicate(utc(2025, 4, 1, 9, 0, 0)) is True


def test_parse_time_open_start_date():
    predicate = parse_time("..2025-04-01")

    assert predicate.start is None
    assert predicate.end == utc(2025, 4, 1, 23, 59, 59, 999999)
    assert predicate.end_inclusive is True

    assert predicate(utc(2025, 4, 1, 12, 0, 0)) is True
    assert predicate(utc(2025, 4, 2, 0, 0, 0)) is False


def test_inclusive_date_upper_bound_includes_entire_day():
    predicate = parse_time("<=2025-04-01")
    assert predicate(utc(2025, 4, 1, 12))
    assert predicate(utc(2025, 4, 1, 23, 59, 59, 999999))
    assert not predicate(utc(2025, 4, 2))
    assert not parse_time("<=2025-04-01T09:00")(utc(2025, 4, 1, 9, 0, 1))
    assert not parse_time("<2025-04-01")(utc(2025, 4, 1))


def test_parse_time_equals_date_is_whole_day():
    predicate = parse_time("=2025-04-01")

    assert predicate.start == utc(2025, 4, 1, 0, 0, 0)
    assert predicate.end == utc(2025, 4, 1, 23, 59, 59, 999999)
    assert predicate(utc(2025, 4, 1, 12, 0, 0)) is True
    assert predicate(utc(2025, 3, 31, 23, 59, 59, 999999)) is False
    assert predicate(utc(2025, 4, 2, 0, 0, 0)) is False


def test_parse_time_naive_is_treated_as_utc():
    predicate = parse_time(">=2025-04-01T09:00")

    assert predicate.start is not None
    assert predicate.start.tzinfo == timezone.utc
    assert predicate.start == utc(2025, 4, 1, 9, 0, 0)


def test_parse_time_accepts_seconds_space_and_exclusive_ops():
    start = parse_time("2025-04-01 09:00:30..")
    assert start.start == utc(2025, 4, 1, 9, 0, 30)

    exclusive = parse_time(">2025-04-01")
    assert exclusive.start == utc(2025, 4, 1, 0, 0, 0)
    assert exclusive.start_inclusive is False
    assert exclusive(utc(2025, 4, 1, 0, 0, 0)) is False
    assert exclusive(utc(2025, 4, 1, 0, 0, 1)) is True

    less = parse_time("<2025-04-01T09:00")
    assert less.end == utc(2025, 4, 1, 9, 0, 0)
    assert less.end_inclusive is False


@pytest.mark.parametrize("spec", ["", "   ", "garbage", "2025-13-01", ">=not-a-date"])
def test_parse_time_invalid_raises(spec):
    with pytest.raises(NtfsDumpError):
        parse_time(spec)


def test_time_predicate_none_is_false():
    assert parse_time(">=2025-04-01").matches(None) is False
    assert TimePredicate()(None) is False
