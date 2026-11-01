import pytest

from ntfsdump.errors import NtfsDumpError
from ntfsfind import core
from ntfsfind.cli import main


def make_vm(tmp_path, disk_metadata):
    (tmp_path / "vm.vmx").write_text(
        'scsi0:0.present = "TRUE"\nscsi0:0.fileName = "current.vmdk"\n'
    )
    (tmp_path / "vm.vmsd").write_text(
        'snapshot.numSnapshots = "1"\nsnapshot0.uid = "1"\n' + disk_metadata
    )
    return tmp_path


@pytest.mark.parametrize(
    "disk_metadata",
    [
        'snapshot0.numDisks = "0"\n',
        'snapshot0.numDisks = "2"\nsnapshot0.disk0.fileName = "snapshot.vmdk"\n',
        'snapshot0.numDisks = "invalid"\n',
        "",
    ],
)
def test_incomplete_snapshot_does_not_list_current_disks(
    tmp_path, capsys, disk_metadata
):
    source = make_vm(tmp_path, disk_metadata)
    assert main([str(source), "--list-disks", "--snapshot", "1"]) == 1
    output = capsys.readouterr()
    assert "Disk metadata was not found for snapshot 1" in output.err
    assert "current.vmdk" not in output.out
    # An explicit snapshot error must not disable current-state inspection.
    assert main([str(source), "--list-disks"]) == 0
    assert "current.vmdk" in capsys.readouterr().out


@pytest.mark.parametrize(
    "disk_metadata",
    [
        'snapshot0.numDisks = "0"\n',
        'snapshot0.numDisks = "2"\nsnapshot0.disk0.fileName = "snapshot.vmdk"\n',
    ],
)
def test_incomplete_snapshot_is_rejected_before_opening_image(
    tmp_path, monkeypatch, disk_metadata
):
    source = make_vm(tmp_path, disk_metadata)

    def unexpected_image(*args, **kwargs):
        pytest.fail("An incomplete snapshot must not open the current image")

    monkeypatch.setattr(core, "ImageFile", unexpected_image)
    with pytest.raises(
        NtfsDumpError, match="Disk metadata was not found for snapshot 1"
    ):
        core.ntfsfind(source, search_query=".", snapshot="1")
