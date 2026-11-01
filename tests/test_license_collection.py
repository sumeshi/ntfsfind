"""Exercise release notice completeness without contacting package registries."""

import hashlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest


@pytest.fixture
def collector():
    path = Path(__file__).resolve().parents[1] / ".github/scripts/collect_licenses.py"
    spec = importlib.util.spec_from_file_location("release_licenses", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_archive(files):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo("package-20240506/" + name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    data.seek(0)
    return tarfile.open(fileobj=data)


def installed_distribution(tmp_path, notices):
    for name, content in notices.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return SimpleNamespace(
        version="20240506",
        files=list(notices),
        locate_file=lambda path: tmp_path / path,
    )


def test_partial_installed_notices_fetch_matching_source(
    collector, tmp_path, monkeypatch
):
    dist = installed_distribution(tmp_path, {"COPYING": b"GPL original"})
    monkeypatch.setattr(collector, "distribution", lambda name: dist)
    calls = []

    def get_source(name, version):
        calls.append((name, version))
        return source_archive(
            {"COPYING": b"GPL original", "COPYING.LESSER": b"LGPL original"}
        ), {"sha256": "verified-source-checksum"}

    monkeypatch.setattr(collector, "get_source", get_source)
    output = tmp_path / "notices"
    record = collector.collect("libewf-python", output)

    assert calls == [("libewf-python", "20240506")]
    assert "COPYING.LESSER" in record["notices"]
    assert (
        output / "libewf-python-20240506/COPYING.LESSER"
    ).read_bytes() == b"LGPL original"


def test_complete_installed_notices_need_no_network(collector, tmp_path, monkeypatch):
    dist = installed_distribution(
        tmp_path, {"COPYING": b"GPL original", "COPYING.LESSER": b"LGPL original"}
    )
    monkeypatch.setattr(collector, "distribution", lambda name: dist)

    def unexpected_source(*args):
        pytest.fail("Complete installed notices must not fetch source archives")

    monkeypatch.setattr(collector, "get_source", unexpected_source)
    record = collector.collect("libewf-python", tmp_path / "notices")
    assert set(record["notices"]) == {"COPYING", "COPYING.LESSER"}


def test_incomplete_source_notices_block_release(collector, tmp_path, monkeypatch):
    dist = installed_distribution(tmp_path, {"COPYING": b"GPL original"})
    monkeypatch.setattr(collector, "distribution", lambda name: dist)
    monkeypatch.setattr(
        collector,
        "get_source",
        lambda *args: (source_archive({"COPYING": b"GPL original"}), {}),
    )
    with pytest.raises(ValueError, match="COPYING.LESSER"):
        collector.collect("libewf-python", tmp_path / "notices")


@pytest.mark.parametrize("location", ["stdlib", "prefix"])
def test_python_notice_comes_from_running_installation(
    collector, tmp_path, monkeypatch, location
):
    stdlib = tmp_path / "lib"
    prefix = tmp_path / "runtime"
    stdlib.mkdir()
    prefix.mkdir()
    source = (stdlib if location == "stdlib" else prefix) / "LICENSE.txt"
    data = b"Original Python license and bundled third-party notices\n"
    source.write_bytes(data)
    monkeypatch.setattr(collector.sysconfig, "get_path", lambda name: str(stdlib))
    monkeypatch.setattr(collector.sys, "base_prefix", str(prefix))
    output = tmp_path / "notices"

    record = collector.collect_python(output)

    assert (output / f"Python-{record['version']}" / "LICENSE.txt").read_bytes() == data
    assert record["source"]["path"] == str(source)
    assert record["source"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert record["version"].startswith("3.")


def test_missing_python_license_blocks_release(collector, tmp_path, monkeypatch):
    monkeypatch.setattr(collector.sysconfig, "get_path", lambda name: str(tmp_path))
    monkeypatch.setattr(collector.sys, "base_prefix", str(tmp_path))
    with pytest.raises(ValueError, match="Python installation has no license"):
        collector.collect_python(tmp_path / "notices")


def test_pytsk3_requires_every_sleuth_kit_and_talloc_notice(collector):
    required = [
        "pytsk3-20260715.dist-info/licenses/LICENSE",
        "pytsk3-20260715.dist-info/licenses/talloc/LICENSE",
        "sleuthkit/licenses/IBM-LICENSE",
        "sleuthkit/licenses/cpl1.0.txt",
        "sleuthkit/licenses/bsd.txt",
        "sleuthkit/licenses/mit.txt",
    ]
    assert not collector.notices_complete("pytsk3", required[:-1])
    assert collector.notices_complete("pytsk3", required)


def test_pytsk3_collection_includes_pinned_native_license_catalog(
    collector, tmp_path, monkeypatch
):
    dist = installed_distribution(
        tmp_path,
        {
            "pytsk3-20260715.dist-info/licenses/LICENSE": b"Apache notice",
            "pytsk3-20260715.dist-info/licenses/talloc/LICENSE": b"LGPL notice",
        },
    )
    dist.version = collector.PYTSK3_VERSION
    monkeypatch.setattr(collector, "distribution", lambda name: dist)
    source_data = {
        "LICENSE": b"Apache source notice",
        "talloc/LICENSE": b"LGPL source notice",
        "utils/update_source.py": b'SLEUTHKIT_GIT_TAG = "4.15.0"\n',
        "sleuthkit/licenses/IBM-LICENSE": b"IBM source notice",
        "sleuthkit/licenses/cpl1.0.txt": b"CPL source notice",
    }
    monkeypatch.setattr(
        collector,
        "get_source",
        lambda name, version: (
            source_archive(source_data), {"url": "pypi-sdist", "sha256": collector.PYTSK3_SDIST_SHA256}
        ),
    )

    output = tmp_path / "notices"
    record = collector.collect("pytsk3", output)
    component = output / "pytsk3-20260715"

    assert record["native_component"]["version"] == "4.15.0"
    assert collector.notices_complete("pytsk3", record["notices"])
    vendor = Path(collector.__file__).parent / "vendor/sleuthkit-4.15.0/licenses"
    for name in collector.SLEUTHKIT_LICENSES:
        bundled = component / "sleuthkit/licenses" / name
        assert bundled.read_bytes() == (vendor / name).read_bytes()
        assert hashlib.sha256(bundled.read_bytes()).hexdigest() == collector.SLEUTHKIT_LICENSES[name]


def test_pytsk3_collection_rejects_unexpected_sleuth_kit_version(
    collector, tmp_path, monkeypatch
):
    dist = installed_distribution(
        tmp_path, {"pytsk3-20260715.dist-info/licenses/LICENSE": b"Apache notice"}
    )
    dist.version = collector.PYTSK3_VERSION
    monkeypatch.setattr(collector, "distribution", lambda name: dist)
    monkeypatch.setattr(
        collector,
        "get_source",
        lambda *args: (
            source_archive({"utils/update_source.py": b'SLEUTHKIT_GIT_TAG = "4.14.0"\n'}),
            {"sha256": collector.PYTSK3_SDIST_SHA256},
        ),
    )

    with pytest.raises(ValueError, match="pinned Sleuth Kit version"):
        collector.collect("pytsk3", tmp_path / "notices")


def rust_crate(name, version, cargo_toml, files):
    data = io.BytesIO()
    root = f"{name}-{version}"
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for relative, content in {"Cargo.toml": cargo_toml, **files}.items():
            member = tarfile.TarInfo(f"{root}/{relative}")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return data.getvalue()


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.data


def test_collect_locked_crates_keeps_original_paths_and_provenance(
    collector, tmp_path, monkeypatch
):
    archives = {
        "alpha": rust_crate(
            "alpha", "1.0.0", b'[package]\nname="alpha"\nversion="1.0.0"\nlicense="MIT"\n',
            {"LICENSE-MIT": b"Copyright Alpha\nMIT text\n", "src/LICENSE": b"nested alpha notice\n"},
        ),
        "beta": rust_crate(
            "beta", "2.0.0", b'[package]\nname="beta"\nversion="2.0.0"\nlicense="MIT"\n',
            {"LICENSE-MIT": b"Copyright Beta\nMIT text\n"},
        ),
    }
    packages = []
    for name, version in (("alpha", "1.0.0"), ("beta", "2.0.0")):
        packages.append({
            "name": name,
            "version": version,
            "source": "registry+https://github.com/rust-lang/crates.io-index",
            "checksum": hashlib.sha256(archives[name]).hexdigest(),
        })
    lock_data = "".join(
        f'[[package]]\nname = "{p["name"]}"\nversion = "{p["version"]}"\nsource = "{p["source"]}"\nchecksum = "{p["checksum"]}"\n'
        for p in packages
    ).encode()
    monkeypatch.setattr(
        collector, "urlopen",
        lambda url, timeout: FakeResponse(archives["alpha"] if "/alpha/" in url else archives["beta"]),
    )

    notices, records = collector.collect_locked_rust_notices(lock_data, tmp_path)

    alpha = tmp_path / "rust-crates/alpha-1.0.0/LICENSE-MIT"
    beta = tmp_path / "rust-crates/beta-2.0.0/LICENSE-MIT"
    assert alpha.read_bytes() == b"Copyright Alpha\nMIT text\n"
    assert beta.read_bytes() == b"Copyright Beta\nMIT text\n"
    assert (tmp_path / "rust-crates/alpha-1.0.0/src/LICENSE").read_bytes() == b"nested alpha notice\n"
    assert len(records) == 2
    assert records[0]["source"]["sha256"] == packages[0]["checksum"]
    assert records[0]["notices"] == [
        "rust-crates/alpha-1.0.0/LICENSE-MIT",
        "rust-crates/alpha-1.0.0/src/LICENSE",
    ]
    assert len(notices) == 3


def test_locked_crate_checksum_corruption_blocks_collection(collector, tmp_path, monkeypatch):
    archive = rust_crate(
        "alpha", "1.0.0", b'[package]\nname="alpha"\nversion="1.0.0"\nlicense="MIT"\n',
        {"LICENSE-MIT": b"MIT"},
    )
    lock_data = (
        '[[package]]\nname = "alpha"\nversion = "1.0.0"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
        f'checksum = "{"0" * 64}"\n'
    ).encode()
    monkeypatch.setattr(collector, "urlopen", lambda *args, **kwargs: FakeResponse(archive))
    with pytest.raises(ValueError, match="checksum mismatch: alpha 1.0.0"):
        collector.collect_locked_rust_notices(lock_data, tmp_path)


def test_locked_crate_missing_required_mit_text_blocks_collection(collector, tmp_path, monkeypatch):
    archive = rust_crate(
        "alpha", "1.0.0", b'[package]\nname="alpha"\nversion="1.0.0"\nlicense="MIT"\n',
        {"README.md": b"Documentation only"},
    )
    lock_data = (
        '[[package]]\nname = "alpha"\nversion = "1.0.0"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
        f'checksum = "{hashlib.sha256(archive).hexdigest()}"\n'
    ).encode()
    monkeypatch.setattr(collector, "urlopen", lambda *args, **kwargs: FakeResponse(archive))
    with pytest.raises(ValueError, match="no supported license or copyright notice resources"):
        collector.collect_locked_rust_notices(lock_data, tmp_path)


def test_unknown_empty_apache_archive_is_rejected(
    collector, tmp_path, monkeypatch
):
    archive = rust_crate(
        "alpha", "1.0.0",
        b'[package]\nname="alpha"\nversion="1.0.0"\nlicense="MIT OR Apache-2.0"\n',
        {"README.md": b"No license file in this release archive"},
    )
    lock_data = (
        '[[package]]\nname = "alpha"\nversion = "1.0.0"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
        f'checksum = "{hashlib.sha256(archive).hexdigest()}"\n'
    ).encode()
    monkeypatch.setattr(collector, "urlopen", lambda *args, **kwargs: FakeResponse(archive))

    with pytest.raises(ValueError, match="no supported license or copyright notice resources"):
        collector.collect_locked_rust_notices(lock_data, tmp_path)


def test_pyo3_file_notice_exception_requires_exact_lock_identity_and_license(collector):
    package = {"name": "pyo3-file", "version": "0.18.0"}
    checksum = "a39bef38c86a2084dcad332d4fc5aeb53c0022c21ce1853e2ee27e5d8de6b19b"
    metadata = {"license": "MIT/Apache-2.0"}
    exception = collector._matching_rust_notice_exception(package, checksum, metadata)
    assert exception["license_text"] == "rust-crates/mft-0.9.1/LICENSE-APACHE"
    assert collector._matching_rust_notice_exception(
        package, checksum, {"license": "Apache-2.0 AND MIT"}
    ) is None
    assert collector._matching_rust_notice_exception(package, "0" * 64, metadata) is None


def test_mft_root_license_does_not_skip_locked_rust_notices(
    collector, tmp_path, monkeypatch
):
    dist = installed_distribution(tmp_path, {"LICENSE": b"Future root mft license\n"})
    dist.version = "0.10.0"
    monkeypatch.setattr(collector, "distribution", lambda name: dist)
    crate = rust_crate(
        "alpha", "1.0.0", b'[package]\nname="alpha"\nversion="1.0.0"\nlicense="MIT"\n',
        {"LICENSE-MIT": b"Copyright Alpha\nMIT license\n"},
    )
    checksum = hashlib.sha256(crate).hexdigest()
    cargo_lock = (
        '[[package]]\nname = "alpha"\nversion = "1.0.0"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
        f'checksum = "{checksum}"\n'
    ).encode()
    sdist_files = {
        "LICENSE": b"Future root mft license\n",
        "Cargo.lock": cargo_lock,
        "pyproject.toml": b'[project]\nlicense = "MIT"\n',
        "Cargo.toml": b'[package]\nauthors = ["MFT Author"]\n',
    }
    monkeypatch.setattr(
        collector,
        "get_source",
        lambda *args: (source_archive(sdist_files), {"sha256": "verified mft sdist"}),
    )
    monkeypatch.setattr(collector, "urlopen", lambda *args, **kwargs: FakeResponse(crate))

    record = collector.collect("mft", tmp_path / "notices")

    assert record["notices"][0] == "LICENSE"
    assert record["rust_dependencies"]["count"] == 1
    assert "rust-crates/alpha-1.0.0/LICENSE-MIT" in record["notices"]
    assert (tmp_path / "notices/mft-0.10.0/rust-crates/alpha-1.0.0/LICENSE-MIT").is_file()


def test_unrecognized_locked_source_blocks_collection(collector):
    lock = {"package": [{"name": "alpha", "version": "1.0.0", "source": "git+https://example.invalid/repo"}]}
    with pytest.raises(ValueError, match="Unsupported locked Rust dependency source"):
        collector.locked_registry_packages(lock)
