"""Collect notices from installed distributions or verified matching source archives.

Run with the same locked environment used to compile the standalone executable.
No mutable upstream branch is used for license retrieval.
"""
from __future__ import annotations

import hashlib
import io
import json
from importlib.metadata import distribution
from pathlib import Path
import re
import sys
import sysconfig
import tarfile
import tomllib
from urllib.request import urlopen


MIT_PERMISSION = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

RUST_NOTICE_EXCEPTIONS = {
    # This exact registry archive omits its declared MIT/Apache notice files.
    # Its MIT option is unsupported by the archive; the already-collected
    # mft 0.9.1 crate carries the original Apache-2.0 notice text.
    ("pyo3-file", "0.18.0", "a39bef38c86a2084dcad332d4fc5aeb53c0022c21ce1853e2ee27e5d8de6b19b"):
        {
            "license": "MIT/Apache-2.0",
            "license_text": "rust-crates/mft-0.9.1/LICENSE-APACHE",
            "reason": "The checksum-pinned pyo3-file archive contains no original license or copyright files. Its Cargo.toml declares MIT/Apache-2.0, and the collected mft 0.9.1 archive supplies the Apache-2.0 text as the documented licensing option.",
        },
    ("utf16-simd", "0.1.1", "4be118d4436ac3c0d994602e970e2a06eb75eaa096a42e061d533af0ee678b8f"):
        {
            "license": "MIT OR Apache-2.0",
            "license_text": "rust-crates/mft-0.9.1/LICENSE-APACHE",
            "reason": "The checksum-pinned utf16-simd archive contains no original license or copyright files. Its Cargo.toml declares MIT OR Apache-2.0, and the collected mft 0.9.1 archive supplies the Apache-2.0 text as an allowed licensing option.",
        },
}

def is_notice(path: str) -> bool:
    name = Path(path).name.upper()
    return name.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "COPYRIGHT", "UNLICENSE")) or name in {
        "CPL1.0.TXT", "BSD.TXT", "MIT.TXT"
    }


def safe_archive_path(name: str) -> Path:
    """Return an archive path after rejecting absolute and parent traversal paths."""
    path = Path(*Path(name).parts)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe source member: {name}")
    return path


def locked_registry_packages(lock: dict) -> list[dict]:
    """Return the exact registry crates pinned by Cargo.lock."""
    for package in lock.get("package", []):
        source = package.get("source")
        if source and not source.startswith("registry+"):
            raise ValueError(
                f"Unsupported locked Rust dependency source: {package['name']} "
                f"{package['version']} ({source})"
            )
    packages = [
        package for package in lock.get("package", [])
        if package.get("source", "").startswith("registry+")
    ]
    for package in packages:
        if not package.get("checksum"):
            raise ValueError(
                f"Locked Rust dependency has no checksum: {package['name']} {package['version']}"
            )
    return packages


def _crate_license_metadata(crate: tarfile.TarFile, root: str) -> dict:
    """Read Cargo license metadata from a crate archive without trusting its paths."""
    member = next(
        (item for item in crate.getmembers()
         if item.isfile() and item.name == f"{root}/Cargo.toml"),
        None,
    )
    if member is None:
        raise ValueError(f"Rust crate archive is missing {root}/Cargo.toml")
    cargo = tomllib.loads(crate.extractfile(member).read().decode("utf-8"))
    package = cargo.get("package", {})
    return {
        "license": package.get("license"),
        "license_file": package.get("license-file"),
        "authors": package.get("authors", []),
    }


def _matching_rust_notice_exception(package: dict, checksum: str, metadata: dict) -> dict | None:
    exception = RUST_NOTICE_EXCEPTIONS.get((package["name"], package["version"], checksum))
    if exception and metadata.get("license") == exception["license"]:
        return exception
    return None


def collect_locked_rust_notices(lock_data: bytes, destination: Path) -> tuple[list[str], list[dict]]:
    """Collect source notices for every checksum-pinned registry crate in a Cargo lock."""
    lock = tomllib.loads(lock_data.decode("utf-8"))
    packages = locked_registry_packages(lock)
    all_notices = []
    records = []
    unsupported_missing_notices = []
    for package in packages:
        name, version = package["name"], package["version"]
        url = f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
        with urlopen(url, timeout=120) as response:
            crate_data = response.read()
        checksum = hashlib.sha256(crate_data).hexdigest()
        if checksum != package["checksum"]:
            raise ValueError(f"Rust crate checksum mismatch: {name} {version}")
        root = f"{name}-{version}"
        crate_notices = []
        with tarfile.open(fileobj=io.BytesIO(crate_data)) as crate:
            metadata = _crate_license_metadata(crate, root)
            members = crate.getmembers()
            for member in members:
                if not member.isfile() or not member.name.startswith(root + "/"):
                    continue
                relative = safe_archive_path(member.name[len(root) + 1:])
                is_declared_file = metadata.get("license_file") and relative.as_posix() == metadata["license_file"]
                data = crate.extractfile(member).read()
                is_license_catalog = relative.name.upper() == "AUTHORS" and b"LICENSE:" in data.upper()
                if not is_notice(str(relative)) and not is_declared_file and not is_license_catalog:
                    continue
                target_relative = Path("rust-crates") / root / relative
                target = destination / target_relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                crate_notices.append(target_relative.as_posix())
        license_file = metadata.get("license_file")
        if license_file and not any(
            path.removeprefix(f"rust-crates/{root}/") == license_file
            for path in crate_notices
        ):
            raise ValueError(
                f"Rust crate {name} {version} declares license-file {license_file!r} "
                "but the checksum-verified archive does not contain it"
            )
        exception = _matching_rust_notice_exception(package, checksum, metadata)
        if not crate_notices and not exception:
            unsupported_missing_notices.append(f"{name} {version} ({metadata.get('license')!r})")
        all_notices.extend(crate_notices)
        records.append({
            "name": name,
            "version": version,
            "source": {"url": url, "sha256": checksum},
            "license": metadata.get("license"),
            "license_file": metadata.get("license_file"),
            "notices": crate_notices,
        })
        if exception:
            records[-1]["notice_exception"] = exception["reason"]
            records[-1]["notice_exception_license_text"] = exception["license_text"]
    for record in records:
        if "notice_exception_license_text" not in record:
            continue
        license_text = destination / record["notice_exception_license_text"]
        if not license_text.is_file() or not license_text.stat().st_size:
            raise ValueError(
                f"Rust notice exception for {record['name']} {record['version']} "
                f"requires missing license text {record['notice_exception_license_text']}"
            )
    if unsupported_missing_notices:
        raise ValueError(
            "Rust crates contain no supported license or copyright notice resources: "
            + ", ".join(unsupported_missing_notices)
        )
    return all_notices, records


REQUIRED_NOTICES = {
    name: {"COPYING", "COPYING.LESSER"}
    for name in ("libewf-python", "libvhdi-python", "libvmdk-python")
}
PYTSK3_VERSION = "20260715"
PYTSK3_TSK_VERSION = "4.15.0"
PYTSK3_SDIST_SHA256 = "50825f97cb5b9bdf3119466104d78e9bef512dd0a0ce1615aea700ad2f457b8e"
SLEUTHKIT_ARCHIVE = {
    "url": "https://codeload.github.com/sleuthkit/sleuthkit/tar.gz/refs/tags/sleuthkit-4.15.0",
    "sha256": "4888ef54f9b404853712945218b3168696569db9167d7e01ec76e44b6c05c71c",
}
SLEUTHKIT_LICENSES = {
    "IBM-LICENSE": "c44ddab37556dec46db7d443004b3479b298ef0518938c1449794292f2fd7765",
    "cpl1.0.txt": "7b47225a5b77cb7825efc6a4d7e0ac57864c790542cf92f5080ec2bf310c00e5",
    "bsd.txt": "7cdad98efc2f3aba2eefd732eafd7885a178bce0af7d7a5a89c22bd320c6532e",
    "mit.txt": "6f1fcd5e7c1c516d831106390fa786896a37007860f784dd358422802a1fa184",
}
REQUIRED_NOTICE_SUFFIXES = {
    "pytsk3": {
        "talloc/license",
        "sleuthkit/licenses/IBM-LICENSE",
        "sleuthkit/licenses/cpl1.0.txt",
        "sleuthkit/licenses/bsd.txt",
        "sleuthkit/licenses/mit.txt",
        "talloc/LICENSE",
    }
}


def notices_complete(name: str, notices: list[str]) -> bool:
    """Check all license texts required by a package and bundled native code."""
    normalized = {str(path).replace("\\", "/").lower() for path in notices}
    if name in REQUIRED_NOTICE_SUFFIXES:
        apache_license = any(
            path == "license" or path.endswith("/licenses/license")
            for path in normalized
        )
        return apache_license and all(
            any(path.endswith(suffix.lower()) for path in normalized)
            for suffix in REQUIRED_NOTICE_SUFFIXES[name]
        )
    available = {Path(path).name.upper() for path in notices}
    return bool(notices) and REQUIRED_NOTICES.get(name, set()) <= available


def validate_pytsk3_source(archive, source: dict) -> None:
    """Tie the locked pytsk3 sdist to its vendored Sleuth Kit release."""
    if source.get("sha256") != PYTSK3_SDIST_SHA256:
        raise ValueError("Unexpected pytsk3 source checksum; update bundled license provenance")
    updater = next(
        (member for member in archive.getmembers()
         if member.isfile() and member.name.endswith("/utils/update_source.py")),
        None,
    )
    if updater is None:
        raise ValueError("pytsk3 source is missing utils/update_source.py")
    data = archive.extractfile(updater).read().decode("utf-8")
    match = re.search(r'SLEUTHKIT_GIT_TAG\s*=\s*["\']([^"\']+)["\']', data)
    if not match or match.group(1) != PYTSK3_TSK_VERSION:
        raise ValueError("pytsk3 source no longer bundles the pinned Sleuth Kit version")


def collect_sleuthkit_notices(destination: Path) -> list[str]:
    """Copy license texts from the checksum-pinned Sleuth Kit 4.15.0 archive."""
    resource_dir = (
        Path(__file__).resolve().parent / "vendor" /
        f"sleuthkit-{PYTSK3_TSK_VERSION}" / "licenses"
    )
    collected = []
    for filename, expected_hash in SLEUTHKIT_LICENSES.items():
        data = (resource_dir / filename).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError(f"Vendored Sleuth Kit license checksum mismatch: {filename}")
        relative = Path("sleuthkit") / "licenses" / filename
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        collected.append(str(relative))
    return collected


def collect_python(output: Path) -> dict:
    """Copy the original license shipped with the interpreter Nuitka embeds."""
    stdlib = Path(sysconfig.get_path("stdlib"))
    prefix = Path(sys.base_prefix)
    candidates = (
        stdlib / "LICENSE.txt",
        prefix / "LICENSE.txt",  # Windows and python.org installations.
        stdlib / "LICENSE",
        prefix / "LICENSE",
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise ValueError("The running Python installation has no license file")
    version = ".".join(map(str, sys.version_info[:3]))
    destination = output / f"Python-{version}"
    destination.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    (destination / "LICENSE.txt").write_bytes(data)
    return {
        "name": "Python",
        "version": version,
        "implementation": sys.implementation.name,
        "notices": ["LICENSE.txt"],
        "source": {"path": str(source), "sha256": hashlib.sha256(data).hexdigest()},
    }


def get_source(name: str, version: str):
    with urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as response:
        metadata = json.load(response)
    source = next(item for item in metadata["urls"] if item["packagetype"] == "sdist")
    with urlopen(source["url"], timeout=120) as response:
        data = response.read()
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != source["digests"]["sha256"]:
        raise ValueError(f"Source checksum mismatch: {name} {version}")
    return tarfile.open(fileobj=io.BytesIO(data)), {"url": source["url"], "sha256": checksum}


def collect(name: str, output: Path) -> dict:
    dist = distribution(name)
    if name == "pytsk3" and dist.version != PYTSK3_VERSION:
        raise ValueError(f"pytsk3 {PYTSK3_VERSION} is required for pinned Sleuth Kit notices")
    destination = output / f"{name}-{dist.version}"
    destination.mkdir(parents=True, exist_ok=True)
    notices = []
    for path in dist.files or []:
        if name == "pytsk3":
            # Use only notices from the verified sdist and pinned TSK archive below.
            continue
        if is_notice(str(path)):
            # Keep original relative paths to preserve notices with the same basename.
            relative = Path(*Path(str(path)).parts)
            if relative.is_absolute() or ".." in relative.parts:
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(dist.locate_file(path)).read_bytes())
            notices.append(str(relative))
    record = {"name": name, "version": dist.version, "notices": notices}
    if notices_complete(name, notices) and name not in {"pytsk3", "mft"}:
        return record
    archive, source = get_source(name, dist.version)
    record["source"] = source
    with archive:
        if name == "pytsk3":
            validate_pytsk3_source(archive, source)
        for member in archive.getmembers():
            if not member.isfile() or not is_notice(member.name):
                continue
            relative = Path(*Path(member.name).parts[1:])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe source member: {member.name}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
            notices.append(str(relative))
        if name == "pytsk3":
            notices.extend(collect_sleuthkit_notices(destination))
            notices = list(dict.fromkeys(notices))
            record["notices"] = notices
            record["native_component"] = {
                "name": "Sleuth Kit",
                "version": PYTSK3_TSK_VERSION,
                "source": SLEUTHKIT_ARCHIVE,
                "license_catalog": "Sleuth Kit 4.15.0 licenses/README.md: libtsk uses IBM, CPL, MIT, and BSD-3-Clause licensed code",
            }
        if not notices and name == "mft":
            # pymft-rs 0.10.0 declares MIT but omits a full license file in both
            # wheel and sdist. Retain its actual declaration and author metadata
            # alongside the standard MIT terms; do not infer copyright ownership.
            project_member = next(m for m in archive if m.name.count("/") == 1 and m.name.endswith("/pyproject.toml"))
            cargo_member = next(m for m in archive if m.name.count("/") == 1 and m.name.endswith("/Cargo.toml"))
            project_data = archive.extractfile(project_member).read()
            cargo_data = archive.extractfile(cargo_member).read()
            project = tomllib.loads(project_data.decode())
            cargo = tomllib.loads(cargo_data.decode())
            if project["project"]["license"] != "MIT":
                raise ValueError("mft no longer declares MIT; update the notice collector")
            authors = [re.sub(r"\s*<[^>]*>", "", author) for author in cargo["package"]["authors"]]
            (destination / "pyproject.toml").write_bytes(project_data)
            (destination / "Cargo.toml").write_bytes(cargo_data)
            notice = "Declared license: MIT\nPackage authors (Cargo.toml): " + ", ".join(authors) + "\n\n" + MIT_PERMISSION
            (destination / "LICENSE-MIT.txt").write_text(notice)
            notices.extend(["LICENSE-MIT.txt", "pyproject.toml", "Cargo.toml"])
            record["notice_provenance"] = "MIT declaration and author names from verified sdist; standard MIT permission text"
        if name == "mft":
            # Collect locked Rust notices even if a future mft wheel adds its
            # own root license file. The lock is read from the verified sdist.
            lock_member = next(m for m in archive if m.name.count("/") == 1 and m.name.endswith("/Cargo.lock"))
            lock_data = archive.extractfile(lock_member).read()
            rust_notices, rust_crates = collect_locked_rust_notices(lock_data, destination)
            notices.extend(rust_notices)
            (destination / "Cargo.lock").write_bytes(lock_data)
            notices.append("Cargo.lock")
            record["rust_dependencies"] = {
                "scope": "all registry packages in the verified Cargo.lock, including build, development, and platform-specific dependencies",
                "lockfile_sha256": hashlib.sha256(lock_data).hexdigest(),
                "count": len(rust_crates),
                "crates": rust_crates,
            }
    if not notices_complete(name, notices):
        normalized = {str(path).replace("\\", "/").lower() for path in notices}
        missing = {
            suffix for suffix in REQUIRED_NOTICE_SUFFIXES.get(name, set())
            if not any(path.endswith(suffix.lower()) for path in normalized)
        }
        missing |= REQUIRED_NOTICES.get(name, set()) - {Path(path).name.upper() for path in notices}
        raise ValueError(
            f"Incomplete license notices for {name} {dist.version}: "
            f"{', '.join(sorted(missing)) or 'no notices found'}"
        )
    return record


def main():
    project, target = sys.argv[1:]
    if project not in {"ntfsdump", "ntfsfind"}:
        raise ValueError("Expected ntfsdump or ntfsfind")
    output = Path(target)
    output.mkdir(parents=True, exist_ok=True)
    packages = ["ntfsdump", "libewf-python", "libvhdi-python", "libvmdk-python", "pytsk3"]
    if project == "ntfsfind":
        packages += ["ntfsfind", "mft"]
    records = [collect(package, output) for package in packages]
    records.append(collect_python(output))
    (output / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"Collected notices for {len(records)} components in {output}")


if __name__ == "__main__":
    main()
