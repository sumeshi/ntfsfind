import csv
import io
import json
from datetime import datetime
from typing import Any, Optional, Sequence

from ntfsfind.record import Record

_ATTR_ORDER = (
    ("FILE_ATTRIBUTE_HIDDEN", "H"),
    ("FILE_ATTRIBUTE_SYSTEM", "S"),
    ("FILE_ATTRIBUTE_READONLY", "R"),
)

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_size(size: Optional[int]) -> str:
    if size is None:
        return "-"
    for label, factor in (
        ("TiB", 1 << 40),
        ("GiB", 1 << 30),
        ("MiB", 1 << 20),
        ("KiB", 1 << 10),
    ):
        if size >= factor:
            value = size / factor
            if value == int(value):
                return f"{int(value)} {label}"
            return f"{value:.1f} {label}"
    return f"{size} B"


def align_table(rows: Sequence[Sequence[str]]) -> list[str]:
    if not rows:
        return []
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for row in rows:
        line = "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        lines.append(line.rstrip())
    return lines


def render_text(records: Sequence[Record]) -> list[str]:
    return [record.path for record in records]


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _timestamp_dict(record: Record, source: str) -> dict[str, Optional[str]]:
    return {
        "created": _isoformat(getattr(record, f"{source}_created", None)),
        "modified": _isoformat(getattr(record, f"{source}_modified", None)),
        "accessed": _isoformat(getattr(record, f"{source}_accessed", None)),
        "mft_modified": _isoformat(getattr(record, f"{source}_mft_modified", None)),
    }


def render_json(records: Sequence[Record]) -> list[str]:
    lines = []
    for record in records:
        payload = {
            "path": record.path,
            "entry_id": record.entry_id,
            "size": record.size,
            "allocated": record.allocated,
            "dir": record.is_dir,
            "ads": list(record.ads),
            "file_flags": list(record.file_flags),
            "si": _timestamp_dict(record, "si"),
            "fn": _timestamp_dict(record, "fn"),
        }
        lines.append(json.dumps(payload, ensure_ascii=False))
    return lines


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def render_csv(records: Sequence[Record]) -> list[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "path",
            "entry_id",
            "size",
            "allocated",
            "dir",
            "ads",
            "file_flags",
            "si_created",
            "si_modified",
            "si_accessed",
            "si_mft_modified",
            "fn_created",
            "fn_modified",
            "fn_accessed",
            "fn_mft_modified",
        ]
    )
    for record in records:
        writer.writerow(
            [
                record.path,
                record.entry_id,
                _csv_value(record.size),
                _csv_value(record.allocated),
                _csv_value(record.is_dir),
                "|".join(record.ads),
                "|".join(record.file_flags),
                _csv_value(record.si_created),
                _csv_value(record.si_modified),
                _csv_value(record.si_accessed),
                _csv_value(record.si_mft_modified),
                _csv_value(record.fn_created),
                _csv_value(record.fn_modified),
                _csv_value(record.fn_accessed),
                _csv_value(record.fn_mft_modified),
            ]
        )
    return buffer.getvalue().splitlines()


def _state(record: Record) -> str:
    if record.allocated:
        return "ALLOC-DIR" if record.is_dir else "ALLOC-FILE"
    return "DELETED-DIR" if record.is_dir else "DELETED-FILE"


def _attr_text(record: Record) -> str:
    flags = set(record.file_flags)
    letters = "".join(letter for token, letter in _ATTR_ORDER if token in flags)
    return letters or "-"


def _format_timestamp(value: Optional[datetime]) -> str:
    return value.strftime(_TIMESTAMP_FORMAT) if value is not None else "-"


def render_table_rows(
    records: Sequence[Record], timestamp_source: str = "si"
) -> list[list[str]]:
    header = ["ENTRY", "STATE", "SIZE", "CREATED", "MODIFIED", "ATTR", "PATH"]
    rows: list[list[str]] = [header]
    for record in sorted(records, key=lambda item: (item.entry_id, item.path)):
        created, modified = record.stream_timestamp(timestamp_source)
        rows.append(
            [
                str(record.entry_id),
                _state(record),
                format_size(record.size),
                _format_timestamp(created),
                _format_timestamp(modified),
                _attr_text(record),
                record.path,
            ]
        )
    return rows


def format_records(
    records: Sequence[Record],
    output_format: str = "text",
    timestamp_source: str = "si",
) -> list[str]:
    if output_format == "text":
        return render_text(records)
    if output_format == "json":
        return render_json(records)
    if output_format == "csv":
        return render_csv(records)
    if output_format == "table":
        return align_table(render_table_rows(records, timestamp_source))
    raise ValueError(f"Unknown output format: {output_format}")
