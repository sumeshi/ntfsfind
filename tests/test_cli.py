import pytest

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
