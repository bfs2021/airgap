"""Config / output-directory defaults of `airgap audit`.

Precedence for the config file: explicit --config > ./config.yaml in the
current directory > the default config bundled in airgap/data/. Outputs go
to ./outputs in the current directory unless --out is given.
"""
import json
import os
import shutil
from importlib import resources

from airgap import cli
from airgap.sources import FixtureSource

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_CONFIG = os.path.join(_ROOT, "config.yaml")
_FIXTURE = os.path.join(_ROOT, "airgap", "data", "acme_datalake.json")


def _audit(*argv: str) -> int:
    return cli.main(["audit", "--no-llm", *argv])


def _findings(out_dir) -> dict:
    with open(os.path.join(out_dir, "findings.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_bundled_config_matches_repo_example():
    # The packaged default must not drift from the documented example.
    bundled = resources.files("airgap.data").joinpath("config.yaml").read_text(
        encoding="utf-8"
    )
    with open(_REPO_CONFIG, encoding="utf-8") as fh:
        assert bundled == fh.read()


def test_bundled_fixture_is_the_repo_fixture():
    assert len(FixtureSource().fetch().assets) == len(
        FixtureSource(_FIXTURE).fetch().assets
    )


def test_empty_dir_uses_bundled_config_and_writes_to_cwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.resolve_config(None) is None
    assert _audit() == 0
    assert "bundled default" in capsys.readouterr().out
    data = _findings(tmp_path / "outputs")
    assert data["source"] == "fixture"
    assert len(data["findings"]) == 5
    for name in ("report.md", "lineage_graph.html"):
        assert (tmp_path / "outputs" / name).is_file()
    assert len(list((tmp_path / "outputs" / "patches").glob("*.py"))) == 5


def test_cwd_config_beats_bundled_default(tmp_path, monkeypatch, capsys):
    # A ./config.yaml with a relative fixture_path, resolved against its dir.
    shutil.copy(_FIXTURE, tmp_path / "catalog.json")
    with open(_REPO_CONFIG, encoding="utf-8") as fh:
        text = fh.read().replace('fixture_path: ""', "fixture_path: catalog.json")
    # With no PII markers nothing is sensitive, so this config is detectable.
    start = text.index("  pii_markers:")
    end = text.index("  # Consumer entity types")
    text = text[:start] + "  pii_markers: [NoSuchMarker]\n" + text[end:]
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.resolve_config(None) == str(tmp_path / "config.yaml")
    assert _audit() == 0
    assert str(tmp_path / "config.yaml") in capsys.readouterr().out
    assert _findings(tmp_path / "outputs")["findings"] == []


def test_explicit_config_beats_cwd_config(tmp_path, monkeypatch, capsys):
    (tmp_path / "config.yaml").write_text("source: nonsense\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert cli.resolve_config(_REPO_CONFIG) == _REPO_CONFIG
    assert _audit("--config", _REPO_CONFIG) == 0
    capsys.readouterr()
    # Without the flag, the broken ./config.yaml is picked up.
    assert _audit() == 1
    assert "airgap: error: Unknown source: 'nonsense'" in capsys.readouterr().err


def test_relative_out_is_resolved_against_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _audit("--out", "reports/run1") == 0
    assert (tmp_path / "reports" / "run1" / "findings.json").is_file()
    assert not (tmp_path / "outputs").exists()
