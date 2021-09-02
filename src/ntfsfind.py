import io
import re
import argparse
from pathlib import Path
from typing import List, Optional
from multiprocessing import Pool, cpu_count

from ntfsdump import ImageFile
from mft import PyMftParser


def extract_name(line: bytes):
    return line.decode("utf8").split(",")[-1].strip()


def gen_names(mft: bytes, multiprocess: bool) -> List[str]:
    csvparser = PyMftParser(io.BytesIO(mft))
    if multiprocess:
        with Pool(cpu_count()) as pool:
            results = pool.map_async(
                extract_name,
                csvparser.entries_csv()
            )
            return results.get(timeout=None)
    else:
        return [c.decode("utf8").split(",")[-1].strip() for c in csvparser.entries_csv()]


def ntfsfind(imagefile_path: str, search_query: str, volume_num: Optional[int] = None, multiprocess: bool = False) -> List[str]:
    image = ImageFile(Path(imagefile_path).resolve(), volume_num)

    mft = image.main_volume._NtfsVolume__read_file('/$MFT')
    pattern = re.compile(search_query.strip('/'))
    found_records = [i for i in gen_names(mft, multiprocess) if re.match(pattern, i)]

    return found_records


def entry_point():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "search_query", type=str, help="Target File Name (regex is worked.).",
    )
    parser.add_argument("imagefile_path", type=Path, help="raw image file")
    parser.add_argument("--volume-num", "-n", type=int, default=None, help="NTFS volume number(default: autodetect).",)
    parser.add_argument("--multiprocess", "-m", action='store_true', help="flag to run multiprocessing.")
    args = parser.parse_args()

    found_records = ntfsfind(
        imagefile_path=args.imagefile_path,
        search_query=args.search_query,
        volume_num=args.volume_num,
        multiprocess=args.multiprocess,
    )
    print('\n'.join(found_records))


if __name__ == "__main__":
    entry_point()
