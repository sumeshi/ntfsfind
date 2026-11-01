"""Publish MFT exports without overwriting evidence or existing output."""

import errno
import os
from pathlib import Path
import tempfile

from ntfsdump.errors import NtfsDumpError


def require_new_destination(path: Path) -> None:
    # lexists also catches dangling symlinks. Rejecting all existing paths
    # protects image extents/parents and hardlink aliases without depending on
    # which image backend opened the source.
    if os.path.lexists(path):
        raise NtfsDumpError(f"MFT output already exists; choose a new path: {path}")


def _links_unsupported(error: OSError) -> bool:
    # Linux FAT filesystems can report EPERM rather than EOPNOTSUPP. On
    # Windows, unsupported filesystems report ERROR_INVALID_FUNCTION (1) or
    # ERROR_NOT_SUPPORTED (50), whose mapped errno is not always consistent.
    return error.errno in {
        errno.EPERM,
        errno.ENOSYS,
        errno.ENOTSUP,
        errno.EOPNOTSUPP,
    } or getattr(error, "winerror", None) in {1, 50}


def _create_without_links(path: Path, content: bytes) -> None:
    created = None
    try:
        # Exclusive creation also rejects symlinks and a destination created
        # after the initial check. Unlike linking, the new file is visible
        # while it is being written on filesystems without hard links.
        with path.open("xb") as output:
            created = os.fstat(output.fileno())
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        if created is not None:
            try:
                # Do not remove a replacement another process put here while
                # this export was being written.
                if os.path.samestat(created, path.lstat()):
                    path.unlink()
            except OSError:
                pass
        raise


def export_mft(path: Path, content: bytes) -> None:
    """Create an export without replacing an existing path.

    Hard-link publication is atomic when supported. Other filesystems use
    exclusive creation, so a new output can be visible before writing ends.
    """
    require_new_destination(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".ntfsfind-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        # A same-directory hard link atomically publishes the completed file
        # and, unlike replace(), refuses a destination created in the meantime.
        try:
            try:
                os.link(temporary, path)
            except OSError as exc:
                if not _links_unsupported(exc):
                    raise
                _create_without_links(path, content)
        except FileExistsError as exc:
            raise NtfsDumpError(
                f"MFT output already exists; choose a new path: {path}"
            ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
