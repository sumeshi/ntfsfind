import io
import re
import argparse
from pathlib import Path
from typing import List
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


def ntfsfind():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "search_query", type=str, help="Target File Name (regex is worked.).",
    )
    parser.add_argument("imagefile_path", type=Path, help="raw image file")
    parser.add_argument("--volume-num", "-n", type=int, default=None, help="NTFS volume number(default: autodetect).",)
    parser.add_argument("--multiprocess", "-m", action='store_true', help="flag to run multiprocessing.")
    args = parser.parse_args()

    image = ImageFile(args.imagefile_path, args.volume_num)

    mft = image.main_volume._NtfsVolume__read_file('/$MFT')
    pattern = re.compile(args.search_query.strip('/'))
    found_records = [i for i in gen_names(mft, args.multiprocess) if re.match(pattern, i)]
    for record in found_records:
        print(record)


if __name__ == "__main__":
    ntfsfind()
