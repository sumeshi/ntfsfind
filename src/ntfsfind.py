import io
import re
import argparse
from pathlib import Path
from typing import List

from ntfsdump import ImageFile
from mft import PyMftParser


def gen_names(mft: bytes) -> List[str]:
    csvparser = PyMftParser(io.BytesIO(mft))
    return [c.decode("utf8").split(",")[-1].strip() for c in csvparser.entries_csv()]


def ntfsfind():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "search_query", type=str, help="Target File Name (regex is worked.).",
    )
    parser.add_argument("imagefile_path", type=Path, help="raw image file")
    parser.add_argument(
        "--volume-num",
        "-n",
        type=int,
        default=None,
        help="NTFS volume number(default: autodetect).",
    )
    args = parser.parse_args()

    image = ImageFile(args.imagefile_path, args.volume_num)

    mft = image.main_volume._NtfsVolume__read_file('/$MFT')
    pattern = re.compile(args.search_query.strip('/'))
    found_records = [i for i in gen_names(mft) if re.match(pattern, i)]
    for record in found_records:
        print(record)


if __name__ == "__main__":
    ntfsfind()
