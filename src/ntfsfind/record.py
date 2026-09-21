import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Iterable, Iterator, Optional


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
    0x100000: "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS",
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


def parse_flag_tokens(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(str(item) for item in value if str(item))

    text = str(value)
    is_entry_flags = text.startswith("EntryFlags")
    if "(" in text:
        text = text[text.index("(") + 1 :]
        if ")" in text:
            text = text[: text.rindex(")")]

    tokens: list[str] = []
    for part in (item.strip() for item in text.split("|")):
        if not part:
            continue
        if _NUMERIC_FLAG_RE.match(part):
            tokens.extend(_expand_numeric_flags(part, is_entry_flags))
        else:
            tokens.append(part)
    return tuple(tokens)


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


def iter_records(entries: Iterable[Any]) -> Iterator[Record]:
    for entry in entries:
        attributes = list(entry.attributes())
        tokens = parse_flag_tokens(getattr(entry, "flags", None))
        allocated = "ALLOCATED" in tokens
        is_dir = "INDEX_PRESENT" in tokens or "SPECIAL_INDEX_PRESENT" in tokens

        si_content = _first_content(attributes, 16, "StandardInformation")
        fn_content = _first_content(attributes, 48, "FileName")

        ads = []
        for attribute in attributes:
            code = getattr(attribute, "type_code", None)
            name = getattr(attribute, "type_name", None)
            if code == 128 or name == "DATA":
                stream_name = getattr(attribute, "name", "")
                if stream_name:
                    ads.append(stream_name)

        size = None
        if fn_content is not None:
            size = getattr(fn_content, "logical_size", None)
        if size is None:
            size = getattr(entry, "file_size", None)

        if si_content is not None:
            file_flags = parse_flag_tokens(getattr(si_content, "file_flags", None))
        elif fn_content is not None:
            file_flags = parse_flag_tokens(getattr(fn_content, "flags", None))
        else:
            file_flags = ()

        base_path = normalize_path(getattr(entry, "full_path", ""))
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
            code = getattr(attribute, "type_code", None)
            name = getattr(attribute, "type_name", None)
            yield replace(
                base,
                path=f"{base_path}:{stream_name}",
                stream_name=stream_name,
                is_data_stream=(code == 128 or name == "DATA"),
            )
