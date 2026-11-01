"""Validate explicit snapshot requests with older ntfsdump backends too."""

import re

from ntfsdump.errors import NtfsDumpError
from ntfsdump.sources import VmwareSource


def validate_selected_snapshot(source: VmwareSource, snapshot_id: str | None) -> None:
    """Reject incomplete metadata before a backend can fall back to current disks.

    ntfsdump 3.3.2 omits missing disk filenames while parsing VMSD metadata,
    and may fall back to the current VMX for an empty snapshot. Compare the
    parsed disk list with the declared count until the dependency supplies
    this validation itself.
    """
    if snapshot_id is None:
        return
    snapshot = source.vm.get_snapshot(snapshot_id)
    if snapshot is None:
        raise NtfsDumpError(f"Snapshot ID {snapshot_id} was not found.")

    message = f"Disk metadata was not found for snapshot {snapshot_id}."
    if not snapshot.disks or source.vm.vmsd_path is None:
        raise NtfsDumpError(message)

    try:
        text = source.vm.vmsd_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise NtfsDumpError(message) from exc
    values = {}
    for line in text.splitlines():
        key, separator, value = line.strip().partition("=")
        if not separator or key.startswith("#"):
            continue
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        values[key.strip()] = value
    prefixes = [
        key[:-3]
        for key, value in values.items()
        if re.fullmatch(r"snapshot\d+\.uid", key) and value == str(snapshot.id)
    ]
    if len(prefixes) != 1:
        raise NtfsDumpError(message)
    try:
        count = int(values.get(prefixes[0] + "numDisks", "0"))
    except ValueError as exc:
        raise NtfsDumpError(message) from exc
    if count <= 0 or len(snapshot.disks) != count:
        raise NtfsDumpError(message)
