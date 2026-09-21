import argparse
import os
import sys
from typing import Iterable, List, Optional, Sequence
from traceback import format_exc
from importlib.metadata import version, PackageNotFoundError

from ntfsdump.errors import NtfsDumpError
from ntfsdump.formats import VALID_IMAGE_FORMATS
from ntfsdump.formats.vmdk import probe_media_size
from ntfsdump.sources import SourceResolver, VmwareSource
from ntfsdump.vmware import NO_DISKS_MESSAGE, NO_SNAPSHOT_METADATA_MESSAGE
from ntfsfind.core import ntfsfind

_EPILOG = """\
examples:
  ntfsfind evidence.raw '.*\\.evtx'
      search an image (format is auto-detected).

  ntfsfind evidence.E01 '.*\\.evtx'
      E01 images are auto-detected too.

  ntfsfind evidence.bin --image-format raw '.*\\.evtx'
      force the image format when the signature is not recognizable.

  ntfsfind ./WindowsVM --list-snapshots
      list VMware snapshots (ID/NAME/CREATED/PARENT). Use an ID with -s.

  ntfsfind ./WindowsVM -s 5 '.*\\.evtx'
      search the NTFS as it was at snapshot 5, directly from the delta chain.

  ntfsfind ./WindowsVM --list-disks
      list virtual disks (ID/NODE/SIZE/VMDK). Use an ID with -d.

  ntfsfind ./WindowsVM -s 5 -d 1 '.*\\.evtx'
      combine snapshot and disk selection.

  ntfsfind --out-mft /tmp/my_mft.bin evidence.raw
      export $MFT only (no search query required).

  ntfsfind evidence.raw -e evtx,exe --size '>=1MB' --created '>=2025-01-01'
      combine extension, size and timestamp filters (AND).

  ntfsfind evidence.raw --path /Windows/System32 --deleted-only
      list deleted records under a path prefix.

  ntfsfind evidence.raw '.*\\.ps1' --output-format json
      emit one JSON object per record for piping/post-processing.

  ntfsfind evidence.raw -e exe --size '>=10MB' --output-format table
      render an aligned table for human review.

note:
  'table' is intended for human review. Use 'text' (default), 'json' or 'csv'
  when piping output to another tool such as ntfsdump.
"""


def get_version(name: str) -> str:
    try:
        from ntfsfind.__about__ import __version__

        return __version__
    except ImportError:
        pass
    try:
        return version(name)
    except PackageNotFoundError:
        return ""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ntfsfind",
        description=(
            "An efficient tool for searching files, directories, and alternate "
            "data streams directly from NTFS images and VMware VM directories "
            "without mounting them."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version", "-V", action="version", version=get_version("ntfsfind")
    )
    parser.add_argument(
        "--volume",
        "-n",
        type=int,
        default=None,
        help="target NTFS volume number (default: auto-detect system volume).",
    )
    parser.add_argument(
        "--snapshot",
        "-s",
        type=str,
        default=None,
        help=(
            "VMware snapshot UID to read, as shown by --list-snapshots. "
            "Reads the NTFS as it was at that point in time, directly from the "
            "delta chain (default: current VM state)."
        ),
    )
    parser.add_argument(
        "--disk",
        "-d",
        type=int,
        default=None,
        help=(
            "VMware virtual disk ID to read, as shown by --list-disks. "
            "With a single disk it is selected automatically; with multiple "
            "disks this option is required."
        ),
    )
    parser.add_argument(
        "--list-snapshots",
        action="store_true",
        help=(
            "list VMware snapshots (ID/NAME/CREATED/PARENT) found in the "
            "SOURCE and exit. Pass an ID to --snapshot/-s to read that state."
        ),
    )
    parser.add_argument(
        "--list-disks",
        action="store_true",
        help=(
            "list VMware virtual disks (ID/NODE/SIZE/VMDK) found in the "
            "SOURCE and exit. Pass an ID to --disk/-d to read that disk."
        ),
    )
    parser.add_argument(
        "--image-format",
        type=str,
        default=None,
        choices=list(VALID_IMAGE_FORMATS),
        help="force the input image format instead of auto-detection.",
    )
    parser.add_argument(
        "--ignore-case",
        "-i",
        action="store_true",
        help="flag to search with ignorecase.",
    )
    parser.add_argument(
        "--fixed-strings",
        "-F",
        action="store_true",
        help="interpret search_query as a fixed string, not a regular expression.",
    )
    parser.add_argument(
        "--multiprocess", "-m", action="store_true", help="flag to run multiprocessing."
    )
    parser.add_argument(
        "--out-mft",
        type=str,
        default=None,
        help="export the parsed $MFT to the specified file path.",
    )
    parser.add_argument(
        "--extension",
        "-e",
        type=str,
        default=None,
        help=(
            "comma-separated extension filter (e.g. 'evtx,exe'). "
            "Case-insensitive; a leading dot is optional."
        ),
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="match records whose path starts with this prefix (case-insensitive).",
    )
    parser.add_argument(
        "--size",
        type=str,
        default=None,
        help=(
            "size filter such as '>=10MB', '<1KB', '4KB..10MB' or an exact "
            "value (units: B/KB/MB/GB/TB)."
        ),
    )
    parser.add_argument(
        "--created",
        type=str,
        default=None,
        help="creation timestamp filter (e.g. '>=2025-04-01', '2024-01-01..2024-12-31').",
    )
    parser.add_argument(
        "--modified",
        type=str,
        default=None,
        help="modification timestamp filter (same syntax as --created).",
    )
    parser.add_argument(
        "--accessed",
        type=str,
        default=None,
        help="access timestamp filter (same syntax as --created).",
    )
    parser.add_argument(
        "--timestamp-source",
        type=str,
        default="si",
        choices=["si", "fn"],
        help=(
            "timestamp source for filtering and table output: "
            "$STANDARD_INFORMATION (si) or $FILE_NAME (fn)."
        ),
    )
    parser.add_argument(
        "--deleted-only",
        action="store_true",
        help="only records without the ALLOCATED flag.",
    )
    parser.add_argument(
        "--allocated-only",
        action="store_true",
        help="only records with the ALLOCATED flag.",
    )
    parser.add_argument(
        "--files-only",
        action="store_true",
        help="only file records (no directories).",
    )
    parser.add_argument(
        "--dirs-only",
        action="store_true",
        help="only directory records.",
    )
    parser.add_argument(
        "--ads-only",
        action="store_true",
        help="only named data stream (ADS) records.",
    )
    parser.add_argument(
        "--no-ads",
        action="store_true",
        help="exclude named data stream (ADS) records.",
    )
    parser.add_argument(
        "--attributes",
        type=str,
        default=None,
        help=(
            "comma-separated FILE_ATTRIBUTE_* filters (e.g. 'hidden,system'). "
            "All listed attributes must be present."
        ),
    )
    parser.add_argument(
        "--output-format",
        type=str,
        default="text",
        choices=["text", "json", "csv", "table"],
        help=(
            "output format: 'text' (default, paths for piping), 'json', "
            "'csv', or 'table' (human review)."
        ),
    )

    parser.add_argument(
        "source",
        type=str,
        help="disk image file, VMware VM directory, VMX or VMSD path.",
    )
    parser.add_argument(
        "search_query",
        type=str,
        nargs="?",
        default=None,
        help=(
            "Regex search term (e.g '.*\\.evtx'). Can be omitted if --out-mft, "
            "--list-snapshots, --list-disks or any filter option is specified."
        ),
    )

    return parser


def _print_table(rows: Sequence[Sequence[str]]) -> None:
    if not rows:
        return
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        line = "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        print(line.rstrip())


def _format_size(size: Optional[int]) -> str:
    if size is None:
        return "-"
    for label, factor in (
        ("TiB", 1 << 40),
        ("GiB", 1 << 30),
        ("MiB", 1 << 20),
        ("KiB", 1 << 10),
    ):
        if size >= factor:
            value = size / factor
            if value == int(value):
                return f"{int(value)} {label}"
            return f"{value:.1f} {label}"
    return f"{size} B"


def _require_vmware_source(resolved, message: str) -> VmwareSource:
    if not isinstance(resolved, VmwareSource):
        raise NtfsDumpError(message)
    return resolved


def _print_snapshots(resolved) -> None:
    source = _require_vmware_source(resolved, NO_SNAPSHOT_METADATA_MESSAGE)
    snapshots = source.snapshots
    if not snapshots:
        raise NtfsDumpError(NO_SNAPSHOT_METADATA_MESSAGE)

    rows: List[Sequence[str]] = [("ID", "NAME", "CREATED", "PARENT")]
    for snapshot in snapshots:
        created = (
            snapshot.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if snapshot.created_at
            else "-"
        )
        rows.append(
            (
                str(snapshot.id),
                snapshot.name or "-",
                created,
                str(snapshot.parent_id) if snapshot.parent_id else "-",
            )
        )
    _print_table(rows)


def _print_disks(resolved) -> None:
    source = _require_vmware_source(resolved, NO_DISKS_MESSAGE)
    disks = source.disks
    if not disks:
        raise NtfsDumpError(NO_DISKS_MESSAGE)

    rows: List[Sequence[str]] = [("ID", "NODE", "SIZE", "VMDK")]
    for disk in disks:
        size = disk.size if disk.size is not None else probe_media_size(disk.path)
        rows.append(
            (
                str(disk.id),
                disk.node,
                _format_size(size),
                disk.path.name,
            )
        )
    _print_table(rows)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.deleted_only and args.allocated_only:
        parser.error("--deleted-only and --allocated-only cannot be used together")

    if args.files_only and args.dirs_only:
        parser.error("--files-only and --dirs-only cannot be used together")

    if args.ads_only and args.no_ads:
        parser.error("--ads-only and --no-ads cannot be used together")

    has_filter = any(
        (
            args.extension is not None,
            args.path is not None,
            args.size is not None,
            args.created is not None,
            args.modified is not None,
            args.accessed is not None,
            args.allocated_only,
            args.deleted_only,
            args.files_only,
            args.dirs_only,
            args.ads_only,
            args.no_ads,
            args.attributes is not None,
        )
    )

    if not (
        args.search_query
        or args.out_mft
        or args.list_snapshots
        or args.list_disks
        or has_filter
    ):
        parser.error(
            "the following arguments are required: search_query "
            "(unless --out-mft, --list-snapshots, --list-disks or a filter "
            "option such as --extension/--path/--size/--created is used)"
        )

    try:
        if args.list_snapshots or args.list_disks:
            resolved = SourceResolver().resolve(
                args.source,
                image_format=args.image_format,
                snapshot=args.snapshot,
                disk=args.disk,
            )

            if args.list_snapshots:
                _print_snapshots(resolved)
                return 0
            if args.list_disks:
                _print_disks(resolved)
                return 0

        found_records = ntfsfind(
            source=args.source,
            search_query=args.search_query,
            volume=args.volume,
            image_format=args.image_format,
            snapshot=args.snapshot,
            disk=args.disk,
            multiprocess=args.multiprocess,
            ignore_case=args.ignore_case,
            fixed_strings=args.fixed_strings,
            out_mft=args.out_mft,
            extension=args.extension,
            path=args.path,
            size=args.size,
            created=args.created,
            modified=args.modified,
            accessed=args.accessed,
            timestamp_source=args.timestamp_source,
            allocated_only=args.allocated_only,
            deleted_only=args.deleted_only,
            files_only=args.files_only,
            dirs_only=args.dirs_only,
            ads_only=args.ads_only,
            no_ads=args.no_ads,
            attributes=args.attributes,
            output_format=args.output_format,
        )
        if found_records:
            print("\n".join(found_records))
    except NtfsDumpError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupt.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(str(exc) or exc.__class__.__name__, file=sys.stderr)
        if os.environ.get("NTFSDUMP_DEBUG"):
            print(format_exc(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
