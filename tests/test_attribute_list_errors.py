"""Failure cases for external $ATTRIBUTE_LIST reads and parsing."""

from types import SimpleNamespace
import struct

import pytest

from ntfsdump.errors import NtfsDumpError
from ntfsfind.image import _read_nonresident_attribute_lists
from ntfsfind.record import iter_records


def _mft_with_nonresident_list(record_sequence=7, list_size=10):
    record = bytearray(1024)
    record[:4] = b"FILE"
    struct.pack_into("<HH", record, 4, 48, 3)
    record[48:54] = b"\xaa\xaa\xbb\xbb\xcc\xcc"
    record[510:512] = b"\xaa\xaa"
    record[1022:1024] = b"\xaa\xaa"
    struct.pack_into("<H", record, 16, record_sequence)
    struct.pack_into("<H", record, 20, 56)
    struct.pack_into("<I", record, 24, 136)
    struct.pack_into("<I", record, 28, 1024)
    struct.pack_into("<IIBBHHH", record, 56, 32, 72, 1, 0, 0, 0, 3)
    struct.pack_into("<QQHHI", record, 72, 0, 0, 64, 0, 0)
    struct.pack_into("<QQQ", record, 96, 4096, list_size, list_size)
    struct.pack_into("<II", record, 128, 0xFFFFFFFF, 0)
    return bytes(record)


class _FakeImageEntry:
    def __init__(self, sequence, chunks=()):
        self.info = SimpleNamespace(meta=SimpleNamespace(seq=sequence))
        self.chunks = list(chunks)
        self.reads = []

    def read_random(self, offset, amount, attr_type, attr_id):
        self.reads.append((offset, amount, attr_type, attr_id))
        return self.chunks.pop(0) if self.chunks else b""


class _FakeFilesystem:
    def __init__(self, entry):
        self.entry = entry
        self.opened = []

    def open_meta(self, record_id):
        self.opened.append(record_id)
        return self.entry


def test_short_nonresident_attribute_list_read_does_not_publish_partial_bytes():
    entry = _FakeImageEntry(sequence=7, chunks=[b"partial"])
    values = {}

    with pytest.raises(NtfsDumpError, match="Short read for nonresident"):
        _read_nonresident_attribute_lists(
            _FakeFilesystem(entry), _mft_with_nonresident_list(), values
        )

    assert len(entry.reads) == 2
    assert values == {}


def test_nonresident_attribute_list_record_sequence_must_match_mft():
    entry = _FakeImageEntry(sequence=8)
    values = {}

    with pytest.raises(NtfsDumpError, match="sequence changed"):
        _read_nonresident_attribute_lists(
            _FakeFilesystem(entry), _mft_with_nonresident_list(), values
        )

    assert entry.reads == []
    assert values == {}


def _nonresident_list_attribute():
    return SimpleNamespace(
        type_code=32,
        name="",
        raw_value=b"",
        is_resident=False,
        attribute_content=SimpleNamespace(vcn_first=0),
    )


def _valid_list_entry():
    entry = bytearray(26)
    struct.pack_into("<IHBBQQH", entry, 0, 16, 26, 0, 0, 0, 52 | 1 << 48, 0)
    return bytes(entry)


@pytest.mark.parametrize(
    ("damaged_tail", "message"),
    [
        (b"\x10\x00", "entry at end"),
        (struct.pack("<IH", 16, 25) + bytes(20), "entry length"),
        (
            struct.pack("<IHBBQQH", 128, 26, 1, 25, 0, 52 | 1 << 48, 4),
            "entry name",
        ),
    ],
)
def test_iter_records_rejects_malformed_external_list_without_partial_results(
    damaged_tail, message
):
    entry = SimpleNamespace(
        entry_id=52,
        base_entry_id=0,
        base_entry_sequence=0,
        attributes=lambda: [_nonresident_list_attribute()],
    )
    raw_ids = {52: [((32, "", 0), 7)]}
    values = {(52, 7): _valid_list_entry() + damaged_tail}
    records = iter_records(
        [entry], attribute_list_values=values, raw_attribute_ids=raw_ids
    )

    with pytest.raises(NtfsDumpError, match=message):
        next(records)
