import csv
import json
from datetime import datetime, timezone

from ntfsfind.output import (
    align_table,
    format_records,
    format_size,
    render_csv,
    render_json,
    render_table_rows,
    render_text,
)
from ntfsfind.record import Record


def make_record(**overrides):
    values = {
        "path": "/a.txt",
        "base_path": "/a.txt",
        "entry_id": 1,
        "allocated": True,
        "is_dir": False,
        "size": 0,
    }
    values.update(overrides)
    return Record(**values)


def test_format_size():
    assert format_size(None) == "-"
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1024) == "1 KiB"
    assert format_size(1 << 20) == "1 MiB"
    assert format_size(1536) == "1.5 KiB"


def test_render_text_order():
    records = [
        make_record(path="/b.txt", entry_id=2),
        make_record(path="/a.txt", entry_id=1),
    ]
    assert render_text(records) == ["/b.txt", "/a.txt"]


def test_render_json():
    created = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    records = [
        make_record(
            path="/a.txt",
            entry_id=7,
            size=1024,
            allocated=False,
            is_dir=True,
            ads=("Zone.Identifier",),
            file_flags=("FILE_ATTRIBUTE_HIDDEN",),
            si_created=created,
        )
    ]
    lines = render_json(records)
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["path"] == "/a.txt"
    assert payload["entry_id"] == 7
    assert payload["size"] == 1024
    assert payload["allocated"] is False
    assert payload["dir"] is True
    assert payload["ads"] == ["Zone.Identifier"]
    assert payload["file_flags"] == ["FILE_ATTRIBUTE_HIDDEN"]
    assert payload["si"]["created"] == created.isoformat()
    assert payload["si"]["modified"] is None
    assert payload["fn"]["created"] is None
    assert set(payload) == {
        "path",
        "entry_id",
        "size",
        "allocated",
        "dir",
        "ads",
        "file_flags",
        "si",
        "fn",
    }


def test_render_csv():
    created = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    records = [
        make_record(
            path="/a.txt",
            entry_id=7,
            size=1024,
            ads=("a", "b"),
            file_flags=("FILE_ATTRIBUTE_HIDDEN", "FILE_ATTRIBUTE_SYSTEM"),
            si_created=created,
        )
    ]
    lines = render_csv(records)
    rows = list(csv.reader(lines))
    assert rows[0] == [
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
    assert rows[1][0] == "/a.txt"
    assert rows[1][1] == "7"
    assert rows[1][2] == "1024"
    assert rows[1][5] == "a|b"
    assert rows[1][6] == "FILE_ATTRIBUTE_HIDDEN|FILE_ATTRIBUTE_SYSTEM"
    assert rows[1][7] == created.isoformat()
    assert rows[1][8] == ""


def test_render_csv_empty_has_header():
    rows = list(csv.reader(render_csv([])))
    assert len(rows) == 1
    assert rows[0][0] == "path"
    assert rows[0][-1] == "fn_mft_modified"


def test_render_table_rows_header_and_sorting():
    records = [
        make_record(path="/z.txt", entry_id=5),
        make_record(path="/b.txt", entry_id=2),
        make_record(path="/a.txt", entry_id=2),
    ]
    rows = render_table_rows(records)
    assert tuple(rows[0]) == (
        "ENTRY",
        "STATE",
        "SIZE",
        "CREATED",
        "MODIFIED",
        "ATTR",
        "PATH",
    )
    assert [row[0] for row in rows[1:]] == ["2", "2", "5"]
    assert [row[6] for row in rows[1:]] == ["/a.txt", "/b.txt", "/z.txt"]


def test_render_table_rows_state():
    assert render_table_rows([make_record(allocated=True, is_dir=False)])[1][1] == (
        "ALLOC-FILE"
    )
    assert render_table_rows([make_record(allocated=True, is_dir=True)])[1][1] == (
        "ALLOC-DIR"
    )
    assert render_table_rows([make_record(allocated=False, is_dir=False)])[1][1] == (
        "DELETED-FILE"
    )
    assert render_table_rows([make_record(allocated=False, is_dir=True)])[1][1] == (
        "DELETED-DIR"
    )


def test_render_table_rows_attr():
    assert render_table_rows([make_record(file_flags=())])[1][5] == "-"
    hidden = make_record(file_flags=("FILE_ATTRIBUTE_HIDDEN",))
    assert render_table_rows([hidden])[1][5] == "H"
    flags = (
        "FILE_ATTRIBUTE_READONLY",
        "FILE_ATTRIBUTE_SYSTEM",
        "FILE_ATTRIBUTE_HIDDEN",
    )
    assert render_table_rows([make_record(file_flags=flags)])[1][5] == "HSR"


def test_render_table_rows_timestamp_source():
    si_created = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    fn_created = datetime(2025, 6, 7, 8, 9, 10, tzinfo=timezone.utc)
    record = make_record(si_created=si_created, fn_created=fn_created)
    assert render_table_rows([record], "si")[1][3] == "2024-01-01 00:00:00"
    assert render_table_rows([record], "fn")[1][3] == "2025-06-07 08:09:10"


def test_render_table_rows_missing_timestamps():
    rows = render_table_rows([make_record()])
    assert rows[1][3] == "-"
    assert rows[1][4] == "-"


def test_align_table_empty():
    assert align_table([]) == []


def test_align_table_alignment_and_rstrip():
    rows = [["A", "BB"], ["AAA", "B"]]
    lines = align_table(rows)
    assert lines == ["A    BB", "AAA  B"]


def test_format_records_dispatch_and_error():
    record = make_record(path="/a.txt", entry_id=1)
    assert format_records([record], "text") == ["/a.txt"]
    assert format_records([record], "json") == render_json([record])
    assert format_records([record], "csv") == render_csv([record])
    assert format_records([record], "table") == align_table(render_table_rows([record]))
    try:
        format_records([record], "unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
