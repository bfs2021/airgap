"""Detection settings: defaults for a missing detection block, loud errors."""
import os

import pytest
import yaml

from airgap import cli
from airgap.detect.settings import DetectionConfigError, detection_settings

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _repo_detection() -> dict:
    with open(os.path.join(_ROOT, "config.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)["detection"]


def test_missing_block_or_keys_use_bundled_defaults():
    det, notes = detection_settings({"source": "fixture"})
    assert det == _repo_detection()
    assert notes == ["config has no detection block; using the bundled detection defaults"]

    det, notes = detection_settings(
        {"detection": {"pii_markers": ["Kişisel"], "severity": {"high_blast_radius": 2}}}
    )
    assert det["pii_markers"] == ["Kişisel"]
    assert det["human_facing_types"] == ["dashboard", "chart"]
    assert det["severity"] == {"critical_blast_radius": 3, "high_blast_radius": 2}
    assert notes == ["config has no detection.human_facing_types; using the bundled default"]

    assert detection_settings({"detection": _repo_detection()}) == (_repo_detection(), [])


@pytest.mark.parametrize(
    "detection",
    [{"pii_markers": []}, {"pii_markers": ["", "  "]}, {"pii_markers": "PII"},
     {"pii_markers": ["PII", 3]}, ["PII"], {"pii_markers": ["PII"], "severity": 3}],
)
def test_unusable_detection_block_is_rejected(detection):
    with pytest.raises(DetectionConfigError):
        detection_settings({"detection": detection})


def _write_config(tmp_path, detection_yaml: str) -> str:
    p = tmp_path / "c.yaml"
    p.write_text("source: fixture\nfixture_path: \"\"\n" + detection_yaml, encoding="utf-8")
    return str(p)


def test_cli_warns_when_detection_block_is_missing(tmp_path, capsys):
    rc = cli.main(["audit", "--no-llm", "--config", _write_config(tmp_path, ""),
                   "--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert rc == 0
    assert "config has no detection block" in captured.err
    assert "Detection complete: 5 finding(s)" in captured.out


def test_cli_rejects_empty_pii_markers(tmp_path, capsys):
    rc = cli.main(["audit", "--no-llm",
                   "--config", _write_config(tmp_path, "detection:\n  pii_markers: []\n"),
                   "--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "airgap: error: config key 'detection.pii_markers' is empty" in captured.err
    assert not (tmp_path / "out").exists()
