import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Iterable, Iterator, Optional

from ntfsdump.errors import NtfsDumpError


@dataclass(frozen=True)
class Record:
    path: str
    base_path: str
    entry_id: int
    allocated: bool
    is_dir: bool
    size: Optional[int]
    si_created: Optional[datetime] = None
    si_modified: Optional[datetime] = None
    si_accessed: Optional[datetime] = None
    si_mft_modified: Optional[datetime] = None
    fn_created: Optional[datetime] = None
    fn_modified: Optional[datetime] = None
    fn_accessed: Optional[datetime] = None
    fn_mft_modified: Optional[datetime] = None
    file_flags: tuple[str, ...] = ()
    stream_name: Optional[str] = None
    is_data_stream: bool = False
    ads: tuple[str, ...] = ()
    hard_link_count: int = 0

    def stream_timestamp(
        self, source: str
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        return (
            getattr(self, f"{source}_created", None),
            getattr(self, f"{source}_modified", None),
        )


_ENTRY_FLAG_BITS = {
    0x1: "ALLOCATED",
    0x2: "INDEX_PRESENT",
    0x4: "IS_EXTENSION",
    0x8: "SPECIAL_INDEX_PRESENT",
}
_FILE_ATTRIBUTE_BITS = {
    0x1: "FILE_ATTRIBUTE_READONLY",
    0x2: "FILE_ATTRIBUTE_HIDDEN",
    0x4: "FILE_ATTRIBUTE_SYSTEM",
    0x10: "FILE_ATTRIBUTE_DIRECTORY",
    0x20: "FILE_ATTRIBUTE_ARCHIVE",
    0x40: "FILE_ATTRIBUTE_DEVICE",
    0x80: "FILE_ATTRIBUTE_NORMAL",
    0x100: "FILE_ATTRIBUTE_TEMPORARY",
    0x200: "FILE_ATTRIBUTE_SPARSE_FILE",
    0x400: "FILE_ATTRIBUTE_REPARSE_POINT",
    0x800: "FILE_ATTRIBUTE_COMPRESSED",
    0x1000: "FILE_ATTRIBUTE_OFFLINE",
    0x2000: "FILE_ATTRIBUTE_NOT_CONTENT_INDEXED",
    0x4000: "FILE_ATTRIBUTE_ENCRYPTED",
    0x8000: "FILE_ATTRIBUTE_INTEGRITY_STREAM",
    0x10000: "FILE_ATTRIBUTE_VIRTUAL",
    0x20000: "FILE_ATTRIBUTE_NO_SCRUB_DATA",
    0x40000: "FILE_ATTRIBUTE_RECALL_ON_OPEN",
    0x80000: "FILE_ATTRIBUTE_PINNED",
    0x100000: "FILE_ATTRIBUTE_UNPINNED",
    0x400000: "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS",
}
_NUMERIC_FLAG_RE = re.compile(r"^(?:0[xX][0-9a-fA-F]+|\d+)$")


def _expand_numeric_flags(token: str, is_entry_flags: bool) -> tuple[str, ...]:
    value = int(token, 16) if token.lower().startswith("0x") else int(token)
    if value == 0:
        return ()
    bits = _ENTRY_FLAG_BITS if is_entry_flags else _FILE_ATTRIBUTE_BITS
    expanded = [name for bit, name in bits.items() if value & bit]
    remaining = value & ~sum(bits)
    if remaining:
        expanded.append(hex(remaining))
    return tuple(expanded)


def parse_flag_tokens(value: Any, *, entry_flags: bool = False) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(str(item) for item in value if str(item))

    text = str(value)
    is_entry_flags = entry_flags or text.startswith("EntryFlags")
    if "(" in text:
        text = text[text.index("(") + 1 :]
        if ")" in text:
            text = text[: text.rindex(")")]

    tokens: list[str] = []
    for part in (item.strip() for item in text.split("|")):
        if not part or part == "empty":
            continue
        if _NUMERIC_FLAG_RE.match(part):
            tokens.extend(_expand_numeric_flags(part, is_entry_flags))
        else:
            tokens.append(part)
    return tuple(tokens)


def _flags_from(
    owner: Any, field: str, *, entry_flags: bool = False
) -> tuple[str, ...]:
    # mft 0.10 exposes numeric values so we need not parse its display strings.
    # Keep the string fallback for older bindings and compatible test doubles.
    value = getattr(owner, f"{field}_value", None)
    if value is None:
        value = getattr(owner, field, None)
    return parse_flag_tokens(value, entry_flags=entry_flags)


def normalize_path(full_path: Any) -> str:
    path = str(full_path).replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    return path


def _first_content(attributes: list, type_code: int, type_name: str) -> Optional[Any]:
    for attribute in attributes:
        code = getattr(attribute, "type_code", None)
        name = getattr(attribute, "type_name", None)
        if code == type_code or name == type_name:
            return getattr(attribute, "attribute_content", None)
    return None


def _is_data_attribute(attribute: Any) -> bool:
    """Return True when the attribute is an unnamed or named $DATA attribute."""
    code = getattr(attribute, "type_code", None)
    if code is not None:
        return code == 128
    return getattr(attribute, "type_name", None) == "DATA"


def _filename_paths(
    entry: Any,
    attributes: list,
    parents: dict[int, tuple[str, Any, bool]],
) -> Iterator[tuple[str, Any]]:
    """Resolve every long filename using its own parent reference.

    DOS names describe the same link as their long-name counterpart. A reused
    parent record must never attach an old filename to an unrelated directory.
    Keep unresolved names searchable under [UNKNOWN] instead.
    """
    filenames: list[Any] = [
        getattr(attribute, "attribute_content", None)
        for attribute in attributes
        if getattr(attribute, "type_code", None) == 48
        or getattr(attribute, "type_name", None) == "FileName"
    ]
    named: list[Any] = [
        content for content in filenames if getattr(content, "name", None) is not None
    ]
    if not named:
        yield normalize_path(getattr(entry, "full_path", "")), next(
            iter(filenames), None
        )
        return

    def is_dos(content: Any) -> bool:
        return getattr(content, "namespace", None) in (2, "DOS", "Dos")

    long_parents = {
        getattr(content, "parent_entry_id", None)
        for content in named
        if not is_dos(content)
    }
    seen = set()
    for content in named:
        parent_id = getattr(content, "parent_entry_id", None)
        if is_dos(content) and parent_id in long_parents:
            continue
        name = content.name
        parent = parents.get(parent_id) if isinstance(parent_id, int) else None
        original = normalize_path(getattr(entry, "full_path", ""))
        if name == "." and parent_id == getattr(entry, "entry_id", None):
            path = "/" if getattr(entry, "entry_id", None) == 5 else original
        elif parent is not None:
            parent_path, sequence, is_dir = parent
            expected = getattr(content, "parent_entry_sequence", None)
            if is_dir and (expected is None or sequence == expected):
                if parent_id == 5:
                    parent_path = ""
                path = parent_path.rstrip("/") + "/" + name
            else:
                path = "/[UNKNOWN]/" + name
        elif original.startswith("/[UNKNOWN]/"):
            path = (
                original
                if original.rsplit("/", 1)[-1] == name
                else "/[UNKNOWN]/" + name
            )
        else:
            path = "/[UNKNOWN]/" + name
        if path not in seen:
            seen.add(path)
            yield path, content


def _attribute_list_references(
    attributes: list,
    attribute_list_values: dict[tuple[int, int], bytes] | None = None,
    raw_attribute_ids: dict[int, list[tuple[tuple[int, str, int], int]]] | None = None,
    record_id: int | None = None,
) -> list[tuple[int, int, int, int, str, int]]:
    """Read list references, using image-backed values for nonresident lists."""
    references = []
    ids = _attribute_ids_for_record(attributes, record_id, raw_attribute_ids)
    for attribute in attributes:
        if getattr(attribute, "type_code", None) != 32:
            continue
        raw = getattr(attribute, "raw_value", None) or b""
        if not raw and not getattr(attribute, "is_resident", True):
            attr_id = ids.get(id(attribute))
            raw = (
                attribute_list_values.get((record_id, attr_id), b"")
                if attribute_list_values is not None
                and record_id is not None
                and attr_id is not None
                else b""
            )
            if not raw:
                raise NtfsDumpError(
                    "This MFT contains a nonresident $ATTRIBUTE_LIST whose value "
                    "is unavailable. Search the original disk image so its clusters "
                    "can be read."
                )
        position = 0
        while position < len(raw):
            if position + 26 > len(raw):
                raise NtfsDumpError("Malformed $ATTRIBUTE_LIST entry at end of value.")
            code = int.from_bytes(raw[position : position + 4], "little")
            length = int.from_bytes(raw[position + 4 : position + 6], "little")
            if length < 26 or position + length > len(raw):
                raise NtfsDumpError("Malformed $ATTRIBUTE_LIST entry length.")
            name_length = raw[position + 6]
            name_offset = raw[position + 7]
            lowest_vcn = int.from_bytes(raw[position + 8 : position + 16], "little")
            segment = int.from_bytes(raw[position + 16 : position + 24], "little")
            attr_id = int.from_bytes(raw[position + 24 : position + 26], "little")
            name = ""
            if name_length:
                if name_offset < 26 or name_offset + name_length * 2 > length:
                    raise NtfsDumpError("Malformed $ATTRIBUTE_LIST entry name.")
                name = raw[
                    position + name_offset : position + name_offset + name_length * 2
                ].decode("utf-16le", errors="replace")
            reference = (
                code,
                segment & 0xFFFFFFFFFFFF,
                segment >> 48,
                lowest_vcn,
                name,
                attr_id,
            )
            if reference not in references:
                references.append(reference)
            position += length
    return references


def _attribute_ids_for_record(attributes, record_id, raw_attribute_ids):
    """Correlate parser attributes to raw header IDs by exact NTFS signature."""
    if record_id is None or raw_attribute_ids is None:
        return {}
    raw = raw_attribute_ids.get(record_id, ())
    by_signature: dict[tuple[int, str, int], list[int]] = {}
    for signature, attr_id in raw:
        by_signature.setdefault(signature, []).append(attr_id)
    parsed_attributes: list[tuple[Any, tuple[int, str, int]]] = []
    for attribute in attributes:
        code = getattr(attribute, "type_code", None)
        if not isinstance(code, int):
            continue
        content = getattr(attribute, "attribute_content", None)
        signature = (
            code,
            getattr(attribute, "name", "") or "",
            getattr(content, "vcn_first", 0) or 0,
        )
        parsed_attributes.append((attribute, signature))
    parsed_counts = Counter(signature for _, signature in parsed_attributes)
    raw_counts = Counter(
        {signature: len(ids) for signature, ids in by_signature.items()}
    )
    result = {}
    for attribute, signature in parsed_attributes:
        if parsed_counts[signature] != raw_counts[signature]:
            continue
        matches = by_signature.get(signature)
        if matches:
            result[id(attribute)] = matches.pop(0)
    return result


def _merge_extension_attributes(
    entries: list,
    attrs_by_id: dict[int, list],
    attribute_list_values: dict[tuple[int, int], bytes] | None = None,
    raw_attribute_ids: dict[int, list[tuple[tuple[int, str, int], int]]] | None = None,
) -> dict[int, list]:
    """Attach only attributes named by a base record's valid ATTRIBUTE_LIST."""
    merged = {}
    entry_by_id = {getattr(entry, "entry_id", None): entry for entry in entries}
    for entry in entries:
        entry_id = getattr(entry, "entry_id", None)
        base_id = getattr(entry, "base_entry_id", 0)
        if entry_id is None or base_id or getattr(entry, "base_entry_sequence", 0):
            continue
        base_attrs = list(attrs_by_id[entry_id])
        references = _attribute_list_references(
            base_attrs, attribute_list_values, raw_attribute_ids, entry_id
        )
        for code, target_id, sequence, lowest_vcn, name, attr_id in references:
            if target_id == entry_id:
                continue
            target = entry_by_id.get(target_id)
            if (
                target is None
                or not getattr(target, "valid_fixup", True)
                or getattr(target, "base_entry_id", 0) != entry_id
                or getattr(target, "base_entry_sequence", None)
                != getattr(entry, "sequence", None)
                or getattr(target, "sequence", None) != sequence
            ):
                continue
            if raw_attribute_ids is not None and target_id not in raw_attribute_ids:
                raise NtfsDumpError(
                    "Cannot verify a referenced extension attribute ID because "
                    f"MFT record {target_id} has no valid raw attribute headers."
                )
            target_attrs = attrs_by_id.get(target_id, ())
            target_attr_ids = _attribute_ids_for_record(
                target_attrs, target_id, raw_attribute_ids
            )
            for attribute in target_attrs:
                if (
                    getattr(attribute, "type_code", None) == code
                    and getattr(attribute, "name", "") == name
                    and getattr(
                        getattr(attribute, "attribute_content", None),
                        "vcn_first",
                        0,
                    )
                    == lowest_vcn
                    and (
                        raw_attribute_ids is None
                        or target_attr_ids.get(id(attribute)) == attr_id
                    )
                ):
                    base_attrs.append(attribute)
        # Keep every filename (each can describe a hard link), while keeping
        # one DATA attribute per name. Prefer VCN zero so a continuation
        # record cannot create a duplicate stream path or fake size.
        chosen: dict[tuple[Any, Any], Any] = {}
        for attribute in base_attrs:
            key = (
                getattr(attribute, "type_code", None),
                getattr(attribute, "name", ""),
            )
            if not _is_data_attribute(attribute):
                continue
            current = chosen.get(key)
            vcn = getattr(getattr(attribute, "attribute_content", None), "vcn_first", 0)
            current_vcn = (
                getattr(getattr(current, "attribute_content", None), "vcn_first", 0)
                if current is not None
                else None
            )
            if current is None or (vcn == 0 and current_vcn != 0):
                chosen[key] = attribute
        merged[entry_id] = [
            attribute
            for attribute in base_attrs
            if not _is_data_attribute(attribute)
            or chosen.get(
                (getattr(attribute, "type_code", None), getattr(attribute, "name", ""))
            )
            is attribute
        ]
    return merged


def _resolved_parent_paths(
    entries: list, attrs_by_id: dict[int, list]
) -> dict[int, str]:
    """Resolve directory paths through sequence-checked FILE_NAME ancestry."""
    by_id = {getattr(entry, "entry_id", None): entry for entry in entries}
    links = {}
    for entry_id in by_id:
        if entry_id is None:
            continue
        candidates = [
            getattr(attribute, "attribute_content", None)
            for attribute in attrs_by_id.get(entry_id, ())
            if getattr(attribute, "type_code", None) == 48
            or getattr(attribute, "type_name", None) == "FileName"
        ]
        candidates = [
            content
            for content in candidates
            if getattr(content, "name", None) is not None
            and getattr(content, "namespace", None) not in (2, "DOS", "Dos")
        ]
        links[entry_id] = candidates[0] if candidates else None

    paths = {}
    for entry_id, entry in by_id.items():
        if entry_id is None:
            continue
        if links.get(entry_id) is None:
            paths[entry_id] = normalize_path(getattr(entry, "full_path", ""))
            continue
        names = []
        seen = set()
        current_id = entry_id
        missing = False
        while current_id != 5:
            if current_id in seen:
                missing = True
                break
            seen.add(current_id)
            current = by_id.get(current_id)
            content = links.get(current_id)
            if current is None or content is None:
                missing = True
                break
            name = getattr(content, "name", None)
            if not name or name == ".":
                break
            names.append(name)
            parent_id = getattr(content, "parent_entry_id", None)
            parent = by_id.get(parent_id)
            expected = getattr(content, "parent_entry_sequence", None)
            parent_tokens = (
                _flags_from(parent, "flags", entry_flags=True) if parent else ()
            )
            if (
                parent is None
                or (
                    expected is not None
                    and getattr(parent, "sequence", None) != expected
                )
                or not (
                    "INDEX_PRESENT" in parent_tokens
                    or "SPECIAL_INDEX_PRESENT" in parent_tokens
                )
            ):
                missing = True
                break
            if parent_id == 5:
                current_id = 5
                break
            current_id = parent_id
        parts = list(reversed(names))
        if missing:
            parts.insert(0, "[UNKNOWN]")
        paths[entry_id] = "/" + "/".join(parts)
    return paths


def iter_records(
    entries: Iterable[Any],
    *,
    attribute_list_values: dict[tuple[int, int], bytes] | None = None,
    raw_attribute_ids: dict[int, list[tuple[tuple[int, str, int], int]]] | None = None,
) -> Iterator[Record]:
    # Parent records can occur after the file that references them. Build a
    # compact lookup once rather than assuming MFT entry order is directory order.
    entries = list(entries)
    attrs_by_id = {
        int(entry.entry_id): list(entry.attributes())
        for entry in entries
        if getattr(entry, "entry_id", None) is not None
    }
    merged_attrs = _merge_extension_attributes(
        entries, attrs_by_id, attribute_list_values, raw_attribute_ids
    )
    resolved_paths = _resolved_parent_paths(entries, merged_attrs)
    parents = {}
    for entry in entries:
        entry_id = getattr(entry, "entry_id", None)
        if entry_id is not None:
            tokens = _flags_from(entry, "flags", entry_flags=True)
            parents[entry_id] = (
                resolved_paths.get(
                    entry_id, normalize_path(getattr(entry, "full_path", ""))
                ),
                getattr(entry, "sequence", None),
                "INDEX_PRESENT" in tokens or "SPECIAL_INDEX_PRESENT" in tokens,
            )

    for entry in entries:
        if getattr(entry, "base_entry_id", 0) or getattr(
            entry, "base_entry_sequence", 0
        ):
            continue
        entry_id = getattr(entry, "entry_id", None)
        if entry_id is None:
            attributes = list(entry.attributes())
        else:
            attributes = merged_attrs.get(
                entry_id, attrs_by_id.get(entry_id, list(entry.attributes()))
            )
        tokens = _flags_from(entry, "flags", entry_flags=True)
        allocated = "ALLOCATED" in tokens
        is_dir = "INDEX_PRESENT" in tokens or "SPECIAL_INDEX_PRESENT" in tokens

        si_content = _first_content(attributes, 16, "StandardInformation")
        fn_content = _first_content(attributes, 48, "FileName")

        ads = []
        for attribute in attributes:
            if _is_data_attribute(attribute):
                stream_name = getattr(attribute, "name", "")
                if stream_name:
                    ads.append(stream_name)

        # NOTE: attribute ``data_size`` is the length of the MFT attribute
        # record (structure size), NOT the real data size (e.g. $MFT's $DATA
        # reports 72 while the real file is 262144 bytes), so it must never
        # be used as a size source. A joined unnamed $DATA value is the best
        # size source, with entry.file_size and $FILE_NAME as fallbacks.
        size = None
        for attribute in attributes:
            if not _is_data_attribute(attribute):
                continue
            if getattr(attribute, "name", None):
                continue
            content = getattr(attribute, "attribute_content", None)
            content_data = getattr(content, "data", None)
            if isinstance(content_data, (bytes, bytearray)):
                size = len(content_data)
            elif getattr(content, "vcn_first", 0) == 0:
                size = getattr(content, "file_size", None)
            if size is not None:
                break
        if size is None:
            size = getattr(entry, "file_size", None)
        if size is None and fn_content is not None:
            size = getattr(fn_content, "logical_size", None)

        if si_content is not None:
            file_flags = _flags_from(si_content, "file_flags")
        elif fn_content is not None:
            file_flags = _flags_from(fn_content, "flags")
        else:
            file_flags = ()

        for base_path, fn_content in _filename_paths(entry, attributes, parents):
            base = Record(
                path=base_path,
                base_path=base_path,
                entry_id=getattr(entry, "entry_id", 0) or 0,
                allocated=allocated,
                is_dir=is_dir,
                size=size,
                si_created=getattr(si_content, "created", None),
                si_modified=getattr(si_content, "modified", None),
                si_accessed=getattr(si_content, "accessed", None),
                si_mft_modified=getattr(si_content, "mft_modified", None),
                fn_created=getattr(fn_content, "created", None),
                fn_modified=getattr(fn_content, "modified", None),
                fn_accessed=getattr(fn_content, "accessed", None),
                fn_mft_modified=getattr(fn_content, "mft_modified", None),
                file_flags=file_flags,
                ads=tuple(ads),
                hard_link_count=getattr(entry, "hard_link_count", 0) or 0,
            )

            yield base

            for attribute in attributes:
                stream_name = getattr(attribute, "name", "")
                if not stream_name:
                    continue
                # Resident bytes give the stream size directly. Non-resident
                # sizes are valid only in the first extent (VCN 0); continuation
                # records must not contribute their undefined size fields.
                stream_size = None
                content = getattr(attribute, "attribute_content", None)
                content_data = getattr(content, "data", None)
                if isinstance(content_data, (bytes, bytearray)):
                    stream_size = len(content_data)
                elif getattr(content, "vcn_first", None) == 0:
                    stream_size = getattr(content, "file_size", None)
                yield replace(
                    base,
                    path=f"{base_path}:{stream_name}",
                    stream_name=stream_name,
                    is_data_stream=_is_data_attribute(attribute),
                    size=stream_size,
                )
