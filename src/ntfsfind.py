import io
import re
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import Generator

from ntfsdump import ImageFile, NtfsVolume, NtfsFile
from mft import PyMftParser


def load_mft(start_byte: int, path: Path, address: str) -> bytes:
    return subprocess.check_output(
        f"icat -i raw -f ntfs -o {start_byte} {path} {address}", shell=True,
    )


def gen_names(mft: bytes) -> Generator:
    csvparser = PyMftParser(io.BytesIO(mft))
    for c in csvparser.entries_csv():
        yield c.decode("utf8").split(",")[-1].strip()


def ntfsfind():

    if not shutil.which("mmls"):
        print(
            "The Sleuth Kit is not installed. Please execute the command `brew install sleuthkit`"
        )
        exit()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "search_query", type=str, help="Target File Name (regex is worked.).",
    )
    parser.add_argument("imagefile_path", type=Path, help="raw image file")
    parser.add_argument(
        "--volume-num",
        "-n",
        type=int,
        default=2,
        help="NTFS volume number(default: 2, because volume1 is recovery partition).",
    )
    args = parser.parse_args()

    i = ImageFile(args.imagefile_path)
    v = i.volumes[args.volume_num - 1]
    mft_address = v.find_baseaddress(["$MFT"])
    mft = load_mft(start_byte=v.start_byte, path=v.path, address=mft_address)

    pattern = re.compile(args.search_query)

    found_records = [i for i in gen_names(mft) if re.match(pattern, i)]
    for record in found_records:
        print(record)


if __name__ == "__main__":
    ntfsfind()
