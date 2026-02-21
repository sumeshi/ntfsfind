import argparse
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

from ntfsfind.core import ntfsfind


def get_version(name: str) -> str:
    try:
        from ntfsfind.__about__ import __version__
        return __version__
    except ImportError:
        pass
    try:
        return version(name)
    except PackageNotFoundError:
        return ''


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="An efficient tool for search files, directories, and alternate data streams directly from NTFS image files."
    )
    
    # Optional arguments
    parser.add_argument(
        "--version", "-V", action="version", version=get_version("ntfsfind")
    )
    parser.add_argument(
        "--format", "-f", type=str, default="raw",
        help="format of the disk image (default: 'raw'). supported: raw, e01, vhd, vhdx, vmdk."
    )
    parser.add_argument(
        "--volume", "-n", type=int, default=None,
        help="target NTFS volume number (default: auto-detect system volume)."
    )
    parser.add_argument(
        "--ignore-case", "-i", action="store_true",
        help="flag to search with ignorecase."
    )
    parser.add_argument(
        "--fixed-strings", "-F", action="store_true",
        help="interpret search_query as a fixed string, not a regular expression."
    )
    parser.add_argument(
        "--multiprocess", "-m", action="store_true",
        help="flag to run multiprocessing."
    )
    parser.add_argument(
        "--out-mft", type=str, default=None,
        help="export the parsed $MFT to the specified file path."
    )

    parser.add_argument(
        "image", type=str, help="path to the target disk image file or an exported $MFT file."
    )
    parser.add_argument(
        "search_query", type=str, nargs='?', default=None, 
        help="Regex search term (e.g '.*\\.evtx'). Can be omitted if --out-mft is specified."
    )

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    if not args.search_query and not args.out_mft:
        parser.error("the following arguments are required: search_query (unless --out-mft is used)")

    found_records: list[str] = ntfsfind(
        args.image,
        args.search_query,
        args.volume,
        args.format,
        args.multiprocess,
        args.ignore_case,
        args.fixed_strings,
        args.out_mft,
    )
    if found_records:
        print('\n'.join(found_records))

if __name__ == "__main__":
    main()
