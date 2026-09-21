from dataclasses import dataclass
from typing import Callable, List

from ntfsfind.parsers import SizePredicate, TimePredicate, parse_size, parse_time
from ntfsfind.record import Record


def extension_of(path: str) -> str:
    """Return the lowercase extension of the final path element without a leading dot."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def normalize_prefix(value: str) -> str:
    """Normalize a path prefix to lowercase, forward-slash, boundary-free form."""
    text = str(value).replace("\\", "/").strip()
    return text.strip("/").lower()


def normalize_extension(value: str) -> str:
    """Normalize an extension to lowercase without a leading dot."""
    return str(value).strip().lstrip(".").lower()


def normalize_attribute_names(values) -> frozenset[str]:
    """Normalize attribute names such as ``hidden`` or ``file_attribute_hidden``."""
    if values is None:
        return frozenset()

    if isinstance(values, str):
        tokens = values.split(",")
    else:
        tokens = []
        for value in values:
            tokens.extend(str(value).split(","))

    result = set()
    for token in tokens:
        name = token.strip().lower()
        if not name:
            continue
        if name.startswith("file_attribute_"):
            name = name[len("file_attribute_") :]
        name = name.strip().upper()
        if not name:
            continue
        result.add("FILE_ATTRIBUTE_" + name)
    return frozenset(result)


def _normalize_extensions(values) -> frozenset[str]:
    if values is None:
        return frozenset()

    if isinstance(values, str):
        tokens = values.split(",")
    else:
        tokens = []
        for value in values:
            tokens.extend(str(value).split(","))

    result = set()
    for token in tokens:
        name = normalize_extension(token)
        if name:
            result.add(name)
    return frozenset(result)


@dataclass(frozen=True)
class ExtensionFilter:
    extensions: frozenset[str]

    def __call__(self, record: Record) -> bool:
        return extension_of(record.base_path) in self.extensions


@dataclass(frozen=True)
class PathPrefixFilter:
    prefix: str

    def __call__(self, record: Record) -> bool:
        base = normalize_prefix(record.base_path)
        prefix = self.prefix
        if not prefix:
            return True
        if not base.startswith(prefix):
            return False
        if len(base) == len(prefix):
            return True
        return base[len(prefix)] == "/"


@dataclass(frozen=True)
class SizeFilter:
    predicate: SizePredicate

    def __call__(self, record: Record) -> bool:
        return self.predicate(record.size)


@dataclass(frozen=True)
class TimestampFilter:
    predicate: TimePredicate
    field: str
    source: str

    def __call__(self, record: Record) -> bool:
        return self.predicate(getattr(record, f"{self.source}_{self.field}"))


@dataclass(frozen=True)
class AllocationFilter:
    mode: str

    def __call__(self, record: Record) -> bool:
        if self.mode == "allocated":
            return record.allocated
        if self.mode == "deleted":
            return not record.allocated
        return False


@dataclass(frozen=True)
class TypeFilter:
    mode: str

    def __call__(self, record: Record) -> bool:
        if self.mode == "files":
            return not record.is_dir
        if self.mode == "dirs":
            return record.is_dir
        return False


@dataclass(frozen=True)
class AdsFilter:
    mode: str

    def __call__(self, record: Record) -> bool:
        if self.mode == "ads":
            return record.is_data_stream
        if self.mode == "no-ads":
            return not record.is_data_stream
        return False


@dataclass(frozen=True)
class AttributeFilter:
    required: frozenset[str]

    def __call__(self, record: Record) -> bool:
        return self.required <= set(record.file_flags)


def build_filters(
    extension=None,
    path=None,
    size=None,
    created=None,
    modified=None,
    accessed=None,
    timestamp_source="si",
    allocated_only=False,
    deleted_only=False,
    files_only=False,
    dirs_only=False,
    ads_only=False,
    no_ads=False,
    attributes=None,
) -> List[Callable[[Record], bool]]:
    """Build the list of predicates for the given options in contract order."""
    filters: List[Callable[[Record], bool]] = []

    extensions = _normalize_extensions(extension)
    if extensions:
        filters.append(ExtensionFilter(extensions))

    if path is not None:
        prefix = normalize_prefix(path)
        if prefix:
            filters.append(PathPrefixFilter(prefix))

    if size is not None:
        filters.append(SizeFilter(parse_size(size)))

    if created is not None:
        filters.append(
            TimestampFilter(parse_time(created), "created", timestamp_source)
        )

    if modified is not None:
        filters.append(
            TimestampFilter(parse_time(modified), "modified", timestamp_source)
        )

    if accessed is not None:
        filters.append(
            TimestampFilter(parse_time(accessed), "accessed", timestamp_source)
        )

    if allocated_only:
        filters.append(AllocationFilter("allocated"))

    if deleted_only:
        filters.append(AllocationFilter("deleted"))

    if files_only:
        filters.append(TypeFilter("files"))

    if dirs_only:
        filters.append(TypeFilter("dirs"))

    if ads_only:
        filters.append(AdsFilter("ads"))

    if no_ads:
        filters.append(AdsFilter("no-ads"))

    required = normalize_attribute_names(attributes)
    if required:
        filters.append(AttributeFilter(required))

    return filters
