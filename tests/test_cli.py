import pytest

from ntfsfind import cli
from ntfsfind.cli import create_parser, main


def test_parser_accepts_new_cli():
    args = create_parser().parse_args(
        [
            "Windows.vmdk",
            ".*evtx",
            "-s",
            "3",
            "-d",
            "1",
            "--image-format",
            "vmdk",
        ]
    )

    assert args.source == "Windows.vmdk"
    assert args.search_query == ".*evtx"
    assert args.snapshot == "3"
    assert args.disk == 1
    assert args.image_format == "vmdk"


def test_parser_rejects_invalid_image_format():
    with pytest.raises(SystemExit):
        create_parser().parse_args(["evidence.raw", "x", "--image-format", "qcow2"])


@pytest.mark.parametrize("option", ["-f", "--format"])
def test_parser_rejects_removed_format_option(option):
    with pytest.raises(SystemExit):
        create_parser().parse_args([option, "raw", "evidence.raw", "x"])


def test_parser_defaults():
    args = create_parser().parse_args(["evidence.raw", "x"])

    assert args.image_format is None
    assert args.snapshot is None
    assert args.disk is None
    assert args.volume is None


def test_parser_allows_missing_query_with_out_mft():
    args = create_parser().parse_args(["evidence.raw", "--out-mft", "/tmp/m"])

    assert args.search_query is None


def test_main_requires_query_or_action():
    with pytest.raises(SystemExit):
        main(["evidence.raw"])


def test_main_out_mft_copies_mft(tmp_path, capsys):
    src = tmp_path / "evidence.mft"
    src.write_bytes(b"FILE" + b"\x00" * 128)
    dst = tmp_path / "out.mft"

    assert main([str(src), "--out-mft", str(dst)]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert dst.read_bytes() == src.read_bytes()


def test_main_reports_missing_source(capsys):
    assert main(["/nonexistent/evidence.raw", "x"]) == 1

    err = capsys.readouterr().err
    assert "No such file or directory" in err
    assert "Traceback" not in err


def test_parser_new_option_defaults():
    args = create_parser().parse_args(["evidence.raw", "x"])

    assert args.extension is None
    assert args.path is None
    assert args.size is None
    assert args.created is None
    assert args.modified is None
    assert args.accessed is None
    assert args.timestamp_source == "si"
    assert args.deleted_only is False
    assert args.allocated_only is False
    assert args.files_only is False
    assert args.dirs_only is False
    assert args.ads_only is False
    assert args.no_ads is False
    assert args.attributes is None
    assert args.output_format == "text"


def test_parser_accepts_new_options():
    args = create_parser().parse_args(
        [
            "evidence.raw",
            "x",
            "-e",
            "evtx,exe",
            "--path",
            "/Windows/System32",
            "--size",
            ">=1MB",
            "--created",
            ">=2025-01-01",
            "--modified",
            "2024-01-01..2024-12-31",
            "--accessed",
            "<2025-01-01",
            "--timestamp-source",
            "fn",
            "--deleted-only",
            "--files-only",
            "--ads-only",
            "--attributes",
            "hidden,system",
            "--output-format",
            "json",
        ]
    )

    assert args.extension == "evtx,exe"
    assert args.path == "/Windows/System32"
    assert args.size == ">=1MB"
    assert args.created == ">=2025-01-01"
    assert args.modified == "2024-01-01..2024-12-31"
    assert args.accessed == "<2025-01-01"
    assert args.timestamp_source == "fn"
    assert args.deleted_only is True
    assert args.files_only is True
    assert args.ads_only is True
    assert args.attributes == "hidden,system"
    assert args.output_format == "json"


def test_parser_accepts_other_store_true_options():
    args = create_parser().parse_args(
        [
            "evidence.raw",
            "x",
            "--allocated-only",
            "--dirs-only",
            "--no-ads",
        ]
    )

    assert args.allocated_only is True
    assert args.dirs_only is True
    assert args.no_ads is True


def test_parser_rejects_invalid_output_format():
    with pytest.raises(SystemExit):
        create_parser().parse_args(["evidence.raw", "x", "--output-format", "yaml"])


def test_parser_rejects_invalid_timestamp_source():
    with pytest.raises(SystemExit):
        create_parser().parse_args(["evidence.raw", "x", "--timestamp-source", "both"])


@pytest.mark.parametrize(
    "options",
    [
        ["--deleted-only", "--allocated-only"],
        ["--files-only", "--dirs-only"],
        ["--ads-only", "--no-ads"],
    ],
)
def test_main_rejects_conflicting_filters(options):
    with pytest.raises(SystemExit):
        main(["evidence.raw", "x", *options])


def test_main_allows_missing_query_with_filter(monkeypatch):
    captured = {}

    def fake_ntfsfind(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli, "ntfsfind", fake_ntfsfind)

    assert main(["evidence.raw", "-e", "evtx"]) == 0
    assert captured["extension"] == "evtx"
    assert captured["output_format"] == "text"


def test_main_forwards_filters_and_output_format(monkeypatch):
    captured = {}

    def fake_ntfsfind(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli, "ntfsfind", fake_ntfsfind)

    assert (
        main(
            [
                "evidence.raw",
                ".*",
                "--size",
                ">=1MB",
                "--deleted-only",
                "--path",
                "/Windows",
                "--attributes",
                "hidden",
                "--output-format",
                "json",
                "--timestamp-source",
                "fn",
            ]
        )
        == 0
    )

    assert captured["search_query"] == ".*"
    assert captured["size"] == ">=1MB"
    assert captured["deleted_only"] is True
    assert captured["path"] == "/Windows"
    assert captured["attributes"] == "hidden"
    assert captured["output_format"] == "json"
    assert captured["timestamp_source"] == "fn"


def test_main_prints_formatted_lines(monkeypatch, capsys):
    def fake_ntfsfind(**kwargs):
        return ['{"path": "/a"}', '{"path": "/b"}']

    monkeypatch.setattr(cli, "ntfsfind", fake_ntfsfind)

    assert main(["evidence.raw", ".*", "--output-format", "json"]) == 0

    captured = capsys.readouterr()
    assert captured.out == '{"path": "/a"}\n{"path": "/b"}\n'
