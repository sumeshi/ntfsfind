"""Small NTFS FILE-record helpers for metadata absent from the mft binding."""

import struct

from ntfsdump.errors import NtfsDumpError

AttributeSignature = tuple[int, str, int]
AttributeIdentity = tuple[AttributeSignature, int]


def _fixed_record(record: bytes) -> bytes:
    """Apply the update-sequence array to a FILE record copy."""
    if len(record) < 8:
        return record
    usa_offset, usa_count = struct.unpack_from("<HH", record, 4)
    if usa_count < 2 or usa_offset + usa_count * 2 > len(record):
        raise NtfsDumpError("Malformed NTFS update sequence array in FILE record.")
    if usa_count != len(record) // 512 + 1:
        raise NtfsDumpError("Incomplete NTFS update sequence array in FILE record.")
    fixed = bytearray(record)
    marker = record[usa_offset : usa_offset + 2]
    for index in range(1, usa_count):
        tail = index * 512 - 2
        if tail + 2 > len(record):
            raise NtfsDumpError("Malformed NTFS update sequence array in FILE record.")
        if record[tail : tail + 2] != marker:
            raise NtfsDumpError("Invalid update sequence marker in FILE record.")
        fixed[tail : tail + 2] = record[
            usa_offset + index * 2 : usa_offset + index * 2 + 2
        ]
    return bytes(fixed)


def _attributes(record: bytes) -> list[tuple[AttributeSignature, int, bool, int]]:
    if len(record) < 48 or record[:4] not in (b"FILE", b"BAAD"):
        return []
    fixed = _fixed_record(record)
    if not fixed:
        return []
    position = struct.unpack_from("<H", fixed, 20)[0]
    used_size = struct.unpack_from("<I", fixed, 24)[0]
    if position < 48 or used_size < position or used_size > len(fixed):
        raise NtfsDumpError("Malformed attribute bounds in NTFS FILE record.")
    result = []
    terminated = False
    while position + 8 <= used_size:
        code, length = struct.unpack_from("<II", fixed, position)
        if code == 0xFFFFFFFF:
            terminated = True
            break
        if length < (64 if position + 8 < used_size and fixed[position + 8] else 24):
            raise NtfsDumpError("Malformed attribute length in NTFS FILE record.")
        if position + length > used_size:
            raise NtfsDumpError("Malformed attribute in NTFS FILE record.")
        nonresident = bool(fixed[position + 8])
        name_length = fixed[position + 9]
        name_offset = struct.unpack_from("<H", fixed, position + 10)[0]
        attr_id = struct.unpack_from("<H", fixed, position + 14)[0]
        if name_length:
            end = name_offset + name_length * 2
            if name_offset < 16 or end > length:
                raise NtfsDumpError("Malformed attribute name in NTFS FILE record.")
            name = fixed[position + name_offset : position + end].decode(
                "utf-16le", errors="replace"
            )
        else:
            name = ""
        vcn = struct.unpack_from("<Q", fixed, position + 16)[0] if nonresident else 0
        data_size = (
            struct.unpack_from("<Q", fixed, position + 48)[0]
            if nonresident and length >= 56
            else 0
        )
        result.append(((code, name, vcn), attr_id, nonresident, data_size))
        position += length
    if not terminated:
        raise NtfsDumpError("Missing attribute terminator in NTFS FILE record.")
    return result


def attribute_id_signatures(mft: bytes) -> dict[int, list[AttributeIdentity]]:
    """Return raw attribute IDs keyed by record, preserving FILE attribute order."""
    if len(mft) < 32:
        return {}
    record_size = struct.unpack_from("<I", mft, 28)[0]
    if record_size < 512 or len(mft) % record_size:
        return {}
    result = {}
    for record_id, start in enumerate(range(0, len(mft), record_size)):
        try:
            attrs = _attributes(mft[start : start + record_size])
        except NtfsDumpError:
            # A damaged unrelated slot should not prevent searching the rest of
            # the MFT. References to this slot cannot pass raw-ID validation.
            continue
        if attrs:
            result[record_id] = [
                (signature, attr_id) for signature, attr_id, _, _ in attrs
            ]
    return result


def nonresident_attribute_lists(mft: bytes) -> dict[int, list[tuple[int, int, int]]]:
    """Return record -> [(raw attribute ID, lowest VCN, data size)] for lists."""
    if len(mft) < 32:
        return {}
    record_size = struct.unpack_from("<I", mft, 28)[0]
    if record_size < 512 or len(mft) % record_size:
        return {}
    result = {}
    for record_id, start in enumerate(range(0, len(mft), record_size)):
        try:
            attrs = _attributes(mft[start : start + record_size])
        except NtfsDumpError:
            continue
        lists = [
            (attr_id, vcn, size)
            for (code, _name, vcn), attr_id, nonresident, size in attrs
            if code == 32 and nonresident
        ]
        if lists:
            result[record_id] = lists
    return result


def record_sequences(mft: bytes) -> dict[int, int]:
    """Return sequence numbers from FILE slots with valid raw attribute headers."""
    if len(mft) < 32:
        return {}
    record_size = struct.unpack_from("<I", mft, 28)[0]
    if record_size < 512 or len(mft) % record_size:
        return {}
    result = {}
    for record_id, start in enumerate(range(0, len(mft), record_size)):
        record = mft[start : start + record_size]
        try:
            _attributes(record)
        except NtfsDumpError:
            continue
        if record[:4] == b"FILE":
            result[record_id] = struct.unpack_from("<H", record, 16)[0]
    return result
