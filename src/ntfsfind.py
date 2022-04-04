import io
import os
import re
import argparse
from pathlib import Path
from typing import Optional, Literal, Generator
from functools import partial
from concurrent.futures import ProcessPoolExecutor
from importlib.metadata import version, PackageNotFoundError

from ntfsdump.models.ImageFile import ImageFile

from mft import PyMftParser, PyMftEntry


def gen_filepaths(entries: list[PyMftEntry]) -> Generator[str, None, None]:
    for entry in entries:
        yield entry.full_path
        for attribute in entry.attributes():
            if attribute.name:
                yield f"{entry.full_path}:{attribute.name}"


def filter_by_pattern(pattern: re.Pattern, filepath: str) -> str:
    if re.match(pattern, filepath):
        return filepath


def find_records(mft: bytes, pattern: re.Pattern, multiprocess: bool) -> set[str]:
    parser = PyMftParser(io.BytesIO(mft))

    # parallel execute
    if multiprocess:
        CHUNK_SIZE = 10000
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
            return [
                el for el in executor.map(
                    partial(filter_by_pattern, pattern),
                    gen_filepaths(parser.entries()),
                    chunksize=CHUNK_SIZE
                ) if el
            ]

    # serial execute
    else:
        return [filepath for filepath in gen_filepaths(parser.entries()) if filepath and re.match(pattern, filepath)]


def ntfsfind(
    imagefile_path: str,
    search_query: str,
    volume_num: Optional[int] = None,
    file_type: Literal[
        'raw',
        'RAW',
        'e01',
        'E01',
        'vhd',
        'VHD',
        'vhdx',
        'VHDX',
        'vmdk',
        'VMDK',
    ] = 'raw',
    multiprocess: bool = False
) -> list[str]:
    image = ImageFile(Path(imagefile_path).resolve(), volume_num, file_type)

    mft = image.main_volume._NtfsVolume__read_file('/$MFT')
    pattern = re.compile(search_query.strip('/'))

    return find_records(mft, pattern, multiprocess)


def get_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return ''


def entry_point():
    # parse cli arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("search_query", type=str, help="Regex search term (e.g '.*\.evtx').",)
    parser.add_argument("imagefile_path", type=Path, help="Source image file.")
    parser.add_argument("--volume-num", "-n", type=int, default=None, help="Number of the source volume (default: autodetect).",)
    parser.add_argument("--type", "-t", type=str, default='raw', help="Format of the source image file (default: raw(dd-format)).")
    parser.add_argument("--multiprocess", "-m", action='store_true', help="Flag to run multiprocessing.")
    parser.add_argument("--version", "-v", action="version", version=get_version('ntfsfind'))
    args = parser.parse_args()

    found_records: list[str] = ntfsfind(
        args.imagefile_path,
        args.search_query,
        args.volume_num,
        args.type,
        args.multiprocess,
    )
    print('\n'.join(found_records))


if __name__ == "__main__":
    entry_point()
