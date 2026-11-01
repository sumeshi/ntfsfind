"""CSV serialization must round-trip paths, including embedded separators."""

import csv
import io
import subprocess
import sys

import pytest

from ntfsfind import cli
from ntfsfind.output import render_csv
from ntfsfind.record import Record


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\r", "\n", "\r\n"])
def test_csv_cli_preserves_path_and_fields(separator, monkeypatch, capsys):
    path = f'/test_dir/file{separator}name,"quoted".txt'
    record = Record(path, path, 52, True, False, 6, ads=(f"stream{separator}name",))
    monkeypatch.setattr(cli, "ntfsfind", lambda **kwargs: render_csv([record]))

    assert cli.main(["image.raw", ".", "--output-format", "csv"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out, newline="")))
    assert len(rows) == 1
    assert rows[0]["path"] == path
    assert rows[0]["entry_id"] == "52"
    assert rows[0]["ads"] == f"stream{separator}name"


def test_csv_native_mft_preserves_unicode_filename(ntfs_sample, tmp_path):
    from ntfsfind.core import find_records, ntfsfind

    destination = tmp_path / "export.mft"
    ntfsfind(ntfs_sample, out_mft=str(destination))
    real_mft = destination.read_bytes()

    # Keep the UTF-16 length identical so the real MFT layout stays intact.
    content = real_mft.replace(
        "file_1.txt".encode("utf-16le"), "file\u20281.txt".encode("utf-16le")
    )
    lines = find_records(content, None, False, output_format="csv")
    rows = list(csv.DictReader(io.StringIO("\n".join(lines) + "\n", newline="")))
    assert any(row["path"] == "/test_dir/file\u20281.txt" for row in rows)
    assert all(row["entry_id"] is not None for row in rows)


@pytest.mark.parametrize("separator", ["\n", "\r", "\r\n", "\u2028"])
def test_csv_cli_preserves_names_with_windows_stdout(separator, monkeypatch):
    path = f"/test_dir/file{separator}name.txt"
    record = Record(path, path, 52, True, False, 6)
    monkeypatch.setattr(cli, "ntfsfind", lambda **kwargs: render_csv([record]))
    binary = io.BytesIO()
    stdout = io.TextIOWrapper(binary, encoding="utf-8", newline="\r\n")
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    assert cli.main(["image.raw", ".", "--output-format", "csv"]) == 0
    rows = list(
        csv.DictReader(io.StringIO(binary.getvalue().decode("utf-8"), newline=""))
    )
    assert len(rows) == 1
    assert rows[0]["path"] == path


@pytest.mark.parametrize(
    "arguments, expected_code", [(["--version"], 0), (["missing.raw", "."], 1)]
)
def test_module_entrypoint_exit_status(tmp_path, arguments, expected_code):
    result = subprocess.run(
        [sys.executable, "-m", "ntfsfind", *arguments],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected_code
    if expected_code:
        assert "No such file or directory" in result.stderr
    else:
        assert result.stdout.strip()
