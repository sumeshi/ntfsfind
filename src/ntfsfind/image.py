"""Read MFT data from NTFS volumes using the installed ntfsdump backend."""

from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

import pytsk3  # type: ignore[import-not-found]

from ntfsdump.errors import NtfsDumpError
from ntfsdump.sources import SourceResolver

from ntfsfind.raw_attributes import (
    attribute_id_signatures,
    nonresident_attribute_lists,
    record_sequences,
)

_OS_INDICATOR_PATHS = (
    "/Windows",
    "/Program Files",
    "/Program Files (x86)",
    "/ProgramData",
    "/Users",
)


def read_image_mft(
    source: str | Path,
    image_factory: Callable[..., Any],
    *,
    volume: int | None = None,
    image_format: str | None = None,
    snapshot: str | None = None,
    disk: int | None = None,
    attribute_list_values: dict[tuple[int, int], bytes] | None = None,
    raw_attribute_ids: dict[int, list[tuple[tuple[int, str, int], int]]] | None = None,
) -> bytes:
    """Find NTFS partitions by probing filesystems, then read ``/$MFT``.

    ntfsfind is distributed against the independently published ntfsdump
    package, whose partition scan may only recognize type-label prefixes.
    Probe allocated partitions locally so GPT user labels and mixed GPT
    layouts are handled consistently across ntfsdump releases.
    """
    options = dict(
        volume=volume, image_format=image_format, snapshot=snapshot, disk=disk
    )
    backend_error = None
    try:
        backend_image = image_factory(source, **options)
    except (OSError, NtfsDumpError) as exc:
        if isinstance(exc, NtfsDumpError) and not _is_backend_selection_error(exc):
            raise
        backend_error = exc
    else:
        with suppress(Exception):
            backend_image.img_info.close()

    resolved = SourceResolver().resolve(
        source,
        image_format=image_format,
        snapshot=snapshot,
        disk=disk,
    )
    image = resolved.get_img_info()
    try:
        candidates = _find_ntfs_volumes(image)
        if not candidates and backend_error is not None:
            raise backend_error
        if not candidates:
            raise NtfsDumpError("No NTFS volume was found.")

        if volume is not None:
            selected = next((item for item in candidates if item[0] == volume), None)
            if selected is None:
                raise NtfsDumpError(f"NTFS volume {volume} was not found.")
        elif len(candidates) == 1:
            selected = candidates[0]
        else:
            os_candidates = [item for item in candidates if _looks_like_os(item[2])]
            if len(os_candidates) == 1:
                selected = os_candidates[0]
            else:
                listing_items = os_candidates if os_candidates else candidates
                listing = ", ".join(
                    f"{addr}: {description}" for addr, description, _ in listing_items
                )
                if os_candidates:
                    raise NtfsDumpError(
                        "Multiple NTFS volumes look like Windows OS volumes: "
                        f"{listing}. Use --volume to select the main volume explicitly."
                    )
                raise NtfsDumpError(
                    "Multiple NTFS volumes were found, but none of them looks like "
                    f"a Windows OS volume: {listing}. Use --volume to select the "
                    "main volume explicitly."
                )
        mft = _read_mft(selected[2])
        if raw_attribute_ids is not None:
            raw_attribute_ids.update(attribute_id_signatures(mft))
        if attribute_list_values is not None:
            _read_nonresident_attribute_lists(selected[2], mft, attribute_list_values)
        return mft
    finally:
        with suppress(Exception):
            image.close()


def _is_backend_selection_error(error: Exception) -> bool:
    message = str(error)
    return (
        message == "No NTFS volume was found."
        or message.startswith("NTFS volume ")
        and message.endswith(" was not found.")
        or message.startswith("Multiple NTFS volumes ")
    )


def _find_ntfs_volumes(image):
    try:
        table = pytsk3.Volume_Info(image)
    except OSError:
        table = None

    if table is not None:
        sector_size = getattr(image, "logical_sector_size", None)
        if sector_size is None:
            try:
                sector_size = int(image.handle.get_bytes_per_sector())
            except (AttributeError, OSError, TypeError, ValueError):
                sector_size = table.info.block_size
        result = []
        for part in table:
            flags = getattr(part, "flags", pytsk3.TSK_VS_PART_FLAG_ALLOC)
            if not flags & pytsk3.TSK_VS_PART_FLAG_ALLOC:
                continue
            try:
                filesystem = pytsk3.FS_Info(
                    image,
                    sector_size * part.start,
                    pytsk3.TSK_FS_TYPE_NTFS,
                )
            except Exception:
                continue
            result.append(
                (
                    part.addr,
                    part.desc.decode("utf-8", errors="replace"),
                    filesystem,
                )
            )
        if result:
            return result

    try:
        filesystem = pytsk3.FS_Info(image, 0, pytsk3.TSK_FS_TYPE_NTFS)
    except OSError:
        return []
    return [(0, "NTFS (partition image)", filesystem)]


def _looks_like_os(filesystem) -> bool:
    has_windows = False
    marker_count = 0
    for path in _OS_INDICATOR_PATHS:
        try:
            item = filesystem.open(path)
        except Exception:
            continue
        if item.info.name.type == pytsk3.TSK_FS_NAME_TYPE_DIR:
            marker_count += 1
            has_windows |= path == "/Windows"
    return has_windows and marker_count >= 2


def _read_mft(filesystem) -> bytes:
    file = filesystem.open("/$MFT")
    if file.info.meta is None:
        raise NtfsDumpError("MFT metadata was not found for /$MFT")
    size = file.info.meta.size
    content = bytearray()
    while len(content) < size:
        chunk = file.read_random(len(content), min(1024 * 1024, size - len(content)))
        if not chunk:
            raise NtfsDumpError(
                f"Unexpected EOF while reading /$MFT: read {len(content)} of {size} bytes."
            )
        content.extend(chunk)
    return bytes(content)


def _read_nonresident_attribute_lists(filesystem, mft, values) -> None:
    """Read nonresident $ATTRIBUTE_LIST values before closing the image."""
    sequences = record_sequences(mft)
    for record_id, lists in nonresident_attribute_lists(mft).items():
        entry = filesystem.open_meta(record_id)
        meta = getattr(getattr(entry, "info", None), "meta", None)
        if meta is None or getattr(meta, "seq", None) != sequences.get(record_id):
            raise NtfsDumpError(
                "The disk image MFT record sequence changed while reading "
                f"$ATTRIBUTE_LIST for record {record_id}."
            )
        for attr_id, lowest_vcn, size in lists:
            # A continuation extent contributes no independent value. The first
            # extent describes the logical stream and its total data size.
            if lowest_vcn != 0:
                continue
            content = bytearray()
            try:
                while len(content) < size:
                    amount = min(1024 * 1024, size - len(content))
                    chunk = entry.read_random(len(content), amount, 32, attr_id)
                    if not chunk:
                        break
                    content.extend(chunk)
            except Exception as exc:
                raise NtfsDumpError(
                    "Unable to read nonresident $ATTRIBUTE_LIST for MFT "
                    f"record {record_id} (attribute {attr_id})."
                ) from exc
            if len(content) != size:
                raise NtfsDumpError(
                    "Short read for nonresident $ATTRIBUTE_LIST in MFT "
                    f"record {record_id}: read {len(content)} of {size} bytes."
                )
            values[(record_id, attr_id)] = bytes(content)
