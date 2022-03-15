import io
import re
import argparse
from pathlib import Path
from typing import Optional, Literal
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from ntfsdump.models.ImageFile import ImageFile

from mft import PyMftParser, PyMftEntry


def task(pattern: re.Pattern, entry: PyMftEntry) -> set[str]:
    results = list()
    if re.match(pattern, entry.full_path):
        results.append(entry.full_path)
    for attribute in entry.attributes():
        if attribute.name and re.match(pattern, f"{entry.full_path}:{attribute.name}"):
            results.append(f"{entry.full_path}:{attribute.name}")
    return results


def gen_names(mft: bytes, pattern: re.Pattern, multiprocess: bool) -> set[str]:
    parser = PyMftParser(io.BytesIO(mft))

    # parallel execute
    if multiprocess:
        CHUNK_SIZE = 10000

        # assign jobs
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="ntfsfind") as executor:
            resultset = executor.map(partial(task, pattern), parser, chunksize=CHUNK_SIZE)

    # serial execute
    else:
        resultset = [task(pattern, entry) for entry in parser.entries()]

    return sum(resultset, [])

def ntfsfind(
    imagefile_path: str,
    search_query: str,
    volume_num: Optional[int] = None,
    file_type: Literal['raw', 'e01'] = 'raw',
    multiprocess: bool = False
) -> list[str]:
    image = ImageFile(Path(imagefile_path).resolve(), volume_num, file_type)

    mft = image.main_volume._NtfsVolume__read_file('/$MFT')
    pattern = re.compile(search_query.strip('/'))
    found_records = [i for i in gen_names(mft, pattern, multiprocess)]
    # found_records = [i for i in gen_names(mft, multiprocess) if re.match(pattern, i)]

    return found_records


def entry_point():
    # parse cli arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("search_query", type=str, help="Regex search term (e.g '.*\.evtx').",)
    parser.add_argument("imagefile_path", type=Path, help="Source image file.")
    parser.add_argument("--volume-num", "-n", type=int, default=None, help="Number of the source volume (default: autodetect).",)
    parser.add_argument("--type", "-t", type=str, default='raw', help="Format of the source image file (default: raw(dd-format)).")
    parser.add_argument("--multiprocess", "-m", action='store_true', help="Flag to run multiprocessing.")
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
