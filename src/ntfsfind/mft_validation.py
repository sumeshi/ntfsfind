"""Check record boundaries before the native parser can drop a partial record."""

import struct

from ntfsdump.errors import NtfsDumpError


def validate_mft_layout(content: bytes) -> None:
    # Bytes 28..31 of the first FILE record contain its allocated size. Do
    # not assume 1024: volumes can also use 4096-byte (or other) records.
    if len(content) < 32:
        raise NtfsDumpError("Incomplete MFT: the first record header is truncated.")
    if content[:4] not in (b"FILE", b"BAAD"):
        raise NtfsDumpError("Invalid MFT: the first record has no FILE/BAAD signature.")

    record_size = struct.unpack_from("<I", content, 28)[0]
    if record_size < 512 or record_size > 65536 or record_size & (record_size - 1):
        raise NtfsDumpError(f"Invalid MFT record size: {record_size} bytes.")

    remainder = len(content) % record_size
    if remainder:
        raise NtfsDumpError(
            f"Incomplete MFT: {len(content)} bytes is not a multiple of the "
            f"{record_size}-byte record size (last record has {remainder} bytes)."
        )
