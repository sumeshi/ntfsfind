import io
import os
import re
from pathlib import Path
from typing import Optional, Literal, Generator
from functools import partial
from concurrent.futures import ProcessPoolExecutor

from ntfsdump.image import ImageFile
from mft import PyMftParser, PyMftEntry


def is_mft_file(path: str) -> bool:
    try:
        with open(path, 'rb') as f:
            magic = f.read(4)
        return magic in (b"FILE", b"BAAD")
    except Exception:
        return False


def gen_filepaths(entries: list[PyMftEntry]) -> Generator[str, None, None]:
    for entry in entries:
        path = str(entry.full_path)
        if not path.startswith('/'):
            path = '/' + path
            
        yield path
        for attribute in entry.attributes():
            if attribute.name:
                yield f"{path}:{attribute.name}"


def filter_by_pattern(pattern: re.Pattern, filepath: str) -> str:
    if re.search(pattern, filepath):
        return filepath


def find_records(mft: bytes, pattern: re.Pattern, multiprocess: bool) -> list[str]:
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
        return [filepath for filepath in gen_filepaths(parser.entries()) if filepath and re.search(pattern, filepath)]


def ntfsfind(
    image: str,
    search_query: Optional[str] = None,
    volume: Optional[int] = None,
    format: Literal[
        'raw', 'RAW', 'e01', 'E01', 'vhd', 'VHD',
        'vhdx', 'VHDX', 'vmdk', 'VMDK',
    ] = 'raw',
    multiprocess: bool = False,
    ignore_case: bool = False,
    fixed_strings: bool = False,
    out_mft: Optional[str] = None,
) -> list[str]:
    if is_mft_file(image):
        with open(image, 'rb') as f:
            mft_content = f.read()
    else:
        img = ImageFile(Path(image).resolve(), volume, format)
        mft_content = img.main_volume._NtfsVolume__read_file('/$MFT')

    if out_mft:
        with open(out_mft, 'wb') as f:
            f.write(mft_content)
    
    if not search_query:
        return []

    query = re.escape(search_query) if fixed_strings else search_query
    pattern = re.compile(query, re.IGNORECASE) if ignore_case else re.compile(query) 

    return find_records(mft_content, pattern, multiprocess)
