from pathlib import Path

from ntfsfind.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "vmware"
WINDOWS_VM = FIXTURES / "WindowsVM"


def test_list_snapshots_output(capsys):
    assert main([str(WINDOWS_VM), "--list-snapshots"]) == 0
    out = capsys.readouterr().out

    for header in ("ID", "NAME", "CREATED", "PARENT"):
        assert header in out
    assert "Before Windows Update" in out
    assert "Before Investigation" in out


def test_list_disks_output(capsys):
    assert main([str(WINDOWS_VM), "--list-disks"]) == 0
    out = capsys.readouterr().out

    for header in ("ID", "NODE", "SIZE", "VMDK"):
        assert header in out
    assert "scsi0:0" in out
    assert "scsi0:1" in out
    assert "Windows-000003.vmdk" in out
    assert "Data-000001.vmdk" in out


def test_list_snapshots_on_non_vmware_source_errors(capsys, tmp_path):
    raw = tmp_path / "evidence.raw"
    raw.write_bytes(b"\x00" * 8192)

    assert main([str(raw), "--list-snapshots"]) == 1
    err = capsys.readouterr().err
    assert "No VMware snapshot metadata was found." in err


def test_list_disks_on_non_vmware_source_errors(capsys, tmp_path):
    raw = tmp_path / "evidence.raw"
    raw.write_bytes(b"\x00" * 8192)

    assert main([str(raw), "--list-disks"]) == 1
    err = capsys.readouterr().err
    assert "No VMware virtual disks were found." in err


def test_missing_snapshot_errors(capsys):
    assert main([str(WINDOWS_VM), "-s", "42", "x"]) == 1
    err = capsys.readouterr().err
    assert "Snapshot ID 42 was not found." in err


def test_missing_disk_errors(capsys):
    assert main([str(WINDOWS_VM), "-d", "9", "x"]) == 1
    err = capsys.readouterr().err
    assert "Disk ID 9 was not found." in err


def test_vmsd_source_lists_snapshots(capsys):
    vmsd = WINDOWS_VM / "WindowsVM.vmsd"

    assert main([str(vmsd), "--list-snapshots"]) == 0
    out = capsys.readouterr().out
    assert "Before Investigation" in out
