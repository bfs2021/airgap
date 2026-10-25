"""Remediation patches must reflect the latest run, not the first one."""
from __future__ import annotations

from airgap.detect.findings import Finding
from airgap.remediate import generate_patches


def _finding(fid: str = "AIRGAP-R1-001") -> Finding:
    return Finding(
        id=fid,
        rule="R1",
        title="PII leaked into a downstream asset",
        severity="high",
        asset_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,app.users,PROD)",
        asset_name="users",
        leaked_fields=["email"],
    )


def test_rerun_into_the_same_dir_drops_stale_patches(tmp_path):
    written = generate_patches([_finding()], str(tmp_path))
    assert len(written) == 1
    assert (tmp_path / "patches" / "AIRGAP-R1-001.py").is_file()

    assert generate_patches([], str(tmp_path)) == []
    assert list((tmp_path / "patches").iterdir()) == []


def test_hand_written_files_are_left_alone(tmp_path):
    keep = tmp_path / "patches" / "my-own-fix.py"
    keep.parent.mkdir()
    keep.write_text("# hand written\n", encoding="utf-8")

    generate_patches([_finding()], str(tmp_path))
    generate_patches([], str(tmp_path))

    assert keep.is_file()
