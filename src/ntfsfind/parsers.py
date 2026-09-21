import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ntfsdump.errors import NtfsDumpError

_SIZE_UNITS = {
    "": 1,
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}

_SIZE_VALUE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]*)")
_DATE_ONLY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

_SIZE_OPERATORS = (">=", "<=", ">", "<", "=")
_TIME_OPERATORS = (">=", "<=", ">", "<", "=")


@dataclass(frozen=True)
class SizePredicate:
    lower: Optional[int] = None
    lower_inclusive: bool = True
    upper: Optional[int] = None
    upper_inclusive: bool = True

    def __call__(self, value: Optional[int]) -> bool:
        if value is None:
            return False
        if self.lower is not None:
            if self.lower_inclusive and value < self.lower:
                return False
            if not self.lower_inclusive and value <= self.lower:
                return False
        if self.upper is not None:
            if self.upper_inclusive and value > self.upper:
                return False
            if not self.upper_inclusive and value >= self.upper:
                return False
        return True

    def matches(self, value: Optional[int]) -> bool:
        return self(value)


def _parse_size_value(token: str, spec: str) -> int:
    match = _SIZE_VALUE_RE.fullmatch(token.strip())
    if match is None:
        raise NtfsDumpError(f"Invalid size specification: {spec}")
    number = float(match.group(1))
    unit = match.group(2).upper()
    if unit not in _SIZE_UNITS:
        raise NtfsDumpError(f"Invalid size specification: {spec}")
    return int(round(number * _SIZE_UNITS[unit]))


def parse_size(spec: str) -> SizePredicate:
    """Parse a size expression such as ``>=10MB``, ``<1KB`` or ``4KB..10MB``."""
    text = spec.strip()
    if not text:
        raise NtfsDumpError(f"Invalid size specification: {spec}")

    for operator in _SIZE_OPERATORS:
        if text.startswith(operator):
            token = text[len(operator) :]
            value = _parse_size_value(token, spec)
            if operator == ">=":
                return SizePredicate(lower=value, lower_inclusive=True)
            if operator == ">":
                return SizePredicate(lower=value, lower_inclusive=False)
            if operator == "<=":
                return SizePredicate(upper=value, upper_inclusive=True)
            if operator == "<":
                return SizePredicate(upper=value, upper_inclusive=False)
            return SizePredicate(
                lower=value, lower_inclusive=True, upper=value, upper_inclusive=True
            )

    if ".." in text:
        parts = text.split("..")
        if len(parts) != 2:
            raise NtfsDumpError(f"Invalid size specification: {spec}")
        lower_token, upper_token = parts
        lower = _parse_size_value(lower_token, spec) if lower_token.strip() else None
        upper = _parse_size_value(upper_token, spec) if upper_token.strip() else None
        return SizePredicate(
            lower=lower,
            lower_inclusive=True,
            upper=upper,
            upper_inclusive=True,
        )

    value = _parse_size_value(text, spec)
    return SizePredicate(
        lower=value, lower_inclusive=True, upper=value, upper_inclusive=True
    )


@dataclass(frozen=True)
class TimePredicate:
    start: Optional[datetime] = None
    start_inclusive: bool = True
    end: Optional[datetime] = None
    end_inclusive: bool = True

    def __call__(self, value: Optional[datetime]) -> bool:
        if value is None:
            return False
        if self.start is not None:
            if self.start_inclusive and value < self.start:
                return False
            if not self.start_inclusive and value <= self.start:
                return False
        if self.end is not None:
            if self.end_inclusive and value > self.end:
                return False
            if not self.end_inclusive and value >= self.end:
                return False
        return True

    def matches(self, value: Optional[datetime]) -> bool:
        return self(value)


def _parse_time_value(token: str, spec: str) -> tuple[datetime, bool]:
    text = token.strip()
    if not text:
        raise NtfsDumpError(f"Invalid timestamp specification: {spec}")
    is_date_only = _DATE_ONLY_RE.fullmatch(text) is not None
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise NtfsDumpError(f"Invalid timestamp specification: {spec}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value, is_date_only


def _day_start(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _day_end(value: datetime) -> datetime:
    return value.replace(hour=23, minute=59, second=59, microsecond=999999)


def _start_bound(value: datetime, is_date_only: bool) -> datetime:
    return _day_start(value) if is_date_only else value


def _end_bound(value: datetime, is_date_only: bool) -> datetime:
    return _day_end(value) if is_date_only else value


def parse_time(spec: str) -> TimePredicate:
    """Parse a timestamp expression such as ``>=2025-04-01`` or ``2024-01-01..2024-12-31``."""
    text = spec.strip()
    if not text:
        raise NtfsDumpError(f"Invalid timestamp specification: {spec}")

    for operator in _TIME_OPERATORS:
        if text.startswith(operator):
            token = text[len(operator) :]
            value, is_date_only = _parse_time_value(token, spec)
            if operator == ">=":
                return TimePredicate(start=value, start_inclusive=True)
            if operator == ">":
                return TimePredicate(start=value, start_inclusive=False)
            if operator == "<=":
                return TimePredicate(end=value, end_inclusive=True)
            if operator == "<":
                return TimePredicate(end=value, end_inclusive=False)
            if is_date_only:
                return TimePredicate(
                    start=_day_start(value),
                    start_inclusive=True,
                    end=_day_end(value),
                    end_inclusive=True,
                )
            return TimePredicate(
                start=value,
                start_inclusive=True,
                end=value,
                end_inclusive=True,
            )

    if ".." in text:
        parts = text.split("..")
        if len(parts) != 2:
            raise NtfsDumpError(f"Invalid timestamp specification: {spec}")
        start_token, end_token = parts
        start = None
        end = None
        if start_token.strip():
            value, is_date_only = _parse_time_value(start_token, spec)
            start = _start_bound(value, is_date_only)
        if end_token.strip():
            value, is_date_only = _parse_time_value(end_token, spec)
            end = _end_bound(value, is_date_only)
        return TimePredicate(
            start=start,
            start_inclusive=True,
            end=end,
            end_inclusive=True,
        )

    value, is_date_only = _parse_time_value(text, spec)
    if is_date_only:
        return TimePredicate(
            start=_day_start(value),
            start_inclusive=True,
            end=_day_end(value),
            end_inclusive=True,
        )
    return TimePredicate(
        start=value, start_inclusive=True, end=value, end_inclusive=True
    )
