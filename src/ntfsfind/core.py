import io
import os
import re
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
from typing import Callable, Generator, Optional, Sequence, Union

from mft import PyMftEntry, PyMftParser
from ntfsdump.image import ImageFile
from ntfsdump.logger import MetaData

from ntfsfind import output
from ntfsfind.filters import build_filters
from ntfsfind.record import Record, iter_records


def is_mft_file(path: Union[str, Path]) -> bool:
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        return magic in (b"FILE", b"BAAD")
    except Exception:
        return False


def gen_filepaths(entries: list[PyMftEntry]) -> Generator[str, None, None]:
    for record in iter_records(entries):
        yield record.path


def filter_by_pattern(pattern: re.Pattern, filepath: str) -> Optional[str]:
    if re.search(pattern, filepath):
        return filepath
    return None


def _record_matches(
    record: Record,
    filters: Sequence[Callable[[Record], bool]],
    pattern: Optional[re.Pattern],
) -> bool:
    for predicate in filters:
        if not predicate(record):
            return False
    if pattern is not None and pattern.search(record.path) is None:
        return False
    return True


def _filter_record(
    record: Record,
    filters: Sequence[Callable[[Record], bool]],
    pattern: Optional[re.Pattern],
) -> Optional[Record]:
    if _record_matches(record, filters, pattern):
        return record
    return None


def find_records(
    mft: bytes,
    pattern: Optional[re.Pattern],
    multiprocess: bool,
    filters: Sequence[Callable[[Record], bool]] = (),
    output_format: str = "text",
    timestamp_source: str = "si",
) -> list[str]:
    parser = PyMftParser(io.BytesIO(mft))
    records = iter_records(parser.entries())

    if multiprocess:
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
            matched = [
                record
                for record in executor.map(
                    partial(_filter_record, filters=tuple(filters), pattern=pattern),
                    records,
                    chunksize=10000,
                )
                if record is not None
            ]
    else:
        matched = [
            record for record in records if _record_matches(record, filters, pattern)
        ]

    return output.format_records(matched, output_format, timestamp_source)


def ntfsfind(
    source: Union[str, Path],
    search_query: Optional[str] = None,
    volume: Optional[int] = None,
    image_format: Optional[str] = None,
    snapshot: Optional[str] = None,
    disk: Optional[int] = None,
    multiprocess: bool = False,
    ignore_case: bool = False,
    fixed_strings: bool = False,
    out_mft: Optional[str] = None,
    extension=None,
    path=None,
    size=None,
    created=None,
    modified=None,
    accessed=None,
    timestamp_source: str = "si",
    allocated_only: bool = False,
    deleted_only: bool = False,
    files_only: bool = False,
    dirs_only: bool = False,
    ads_only: bool = False,
    no_ads: bool = False,
    attributes=None,
    output_format: str = "text",
    verbose: bool = False,
) -> list[str]:
    # ntfsfind's stdout is consumed as a path list when piped into ntfsdump,
    # so ntfsdump's progress lines must never reach stdout unless explicitly
    # requested via verbose=True. 'danger' messages still go to stderr.
    MetaData.quiet = not verbose

    filters = build_filters(
        extension=extension,
        path=path,
        size=size,
        created=created,
        modified=modified,
        accessed=accessed,
        timestamp_source=timestamp_source,
        allocated_only=allocated_only,
        deleted_only=deleted_only,
        files_only=files_only,
        dirs_only=dirs_only,
        ads_only=ads_only,
        no_ads=no_ads,
        attributes=attributes,
    )

    pattern = None
    if search_query is not None:
        query = re.escape(search_query) if fixed_strings else search_query
        pattern = re.compile(query, re.IGNORECASE) if ignore_case else re.compile(query)

    if is_mft_file(source):
        with open(source, "rb") as f:
            mft_content = f.read()
    else:
        img = ImageFile(
            source,
            volume=volume,
            image_format=image_format,
            snapshot=snapshot,
            disk=disk,
        )
        mft_content = img.main_volume._NtfsVolume__read_file("/$MFT")

    if out_mft:
        with open(out_mft, "wb") as f:
            f.write(mft_content)

    if search_query is None and not filters:
        return []

    if not filters and output_format == "text":
        return find_records(mft_content, pattern, multiprocess)

    return find_records(
        mft_content, pattern, multiprocess, filters, output_format, timestamp_source
    )
