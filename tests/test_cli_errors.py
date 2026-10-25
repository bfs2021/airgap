"""CLI surface: --version, readable errors with exit code 1, token env var."""
import os
import subprocess
import sys

import pytest

import airgap
from airgap import cli

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _audit(*argv: str) -> int:
    return cli.main(["audit", "--no-llm", *argv])


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"airgap {airgap.__version__}"


def test_missing_config_file_is_a_readable_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert _audit("--config", str(tmp_path / "missing.yaml")) == 1
    err = capsys.readouterr().err
    assert err.startswith("airgap: error: config file not found:")
    assert "missing.yaml" in err
    assert not (tmp_path / "outputs").exists()


def test_datahub_source_without_url_is_a_readable_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # no ./config.yaml, so the bundled default
    assert _audit("--source", "datahub") == 1
    err = capsys.readouterr().err
    assert "airgap: error: source 'datahub' needs a DataHub URL" in err
    assert "--url" in err


def test_datahub_lite_without_cli_is_a_readable_error(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "no-such-dir" / "datahub"
    (tmp_path / "config.yaml").write_text(
        f"source: datahub-lite\ndatahub_lite:\n  bin: {missing}\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert _audit() == 1
    err = capsys.readouterr().err
    assert "airgap: error: DataHub CLI not found" in err
    assert str(missing) in err
    assert "datahub_lite.bin" in err


def test_errors_print_no_traceback(tmp_path):
    # End to end through `python -m airgap`, as a user would see it.
    env = dict(os.environ, PYTHONPATH=_ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "airgap", "audit", "--no-llm", "--config", "missing.yaml"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "airgap: error: config file not found: missing.yaml" in proc.stderr


def _cfg_after_overrides(argv: list[str], cfg_token: str = "") -> dict:
    args = cli.build_parser().parse_args(["audit", *argv])
    return cli._apply_overrides({"datahub": {"token": cfg_token}}, args)


def test_token_from_environment(monkeypatch):
    monkeypatch.setenv("AIRGAP_DATAHUB_TOKEN", "from-env")
    assert _cfg_after_overrides([])["datahub"]["token"] == "from-env"
    # The environment variable beats the config file ...
    assert _cfg_after_overrides([], cfg_token="from-config")["datahub"]["token"] == "from-env"
    # ... and --token beats both.
    assert _cfg_after_overrides(["--token", "from-flag"])["datahub"]["token"] == "from-flag"


def test_config_token_is_kept_without_env_or_flag(monkeypatch):
    monkeypatch.delenv("AIRGAP_DATAHUB_TOKEN", raising=False)
    assert _cfg_after_overrides([], cfg_token="from-config")["datahub"]["token"] == "from-config"
    monkeypatch.setenv("AIRGAP_DATAHUB_TOKEN", "")
    assert _cfg_after_overrides([], cfg_token="from-config")["datahub"]["token"] == "from-config"


def test_sample_config_has_no_unused_prose_model():
    import yaml

    with open(os.path.join(_ROOT, "config.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    assert "prose_model" not in cfg["ollama"]


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def _fixture_cfg(tmp_path, fixture_path):
    return _write(tmp_path / "cfg.yaml", f"source: fixture\nfixture_path: {fixture_path}\n")


@pytest.mark.parametrize(
    "case, expected",
    [
        ("missing", "fixture file not found:"),
        ("bad_json", "is not valid JSON: Expecting"),
        ("no_name", "missing the required key 'name'"),
    ],
)
def test_broken_fixture_is_a_readable_error(tmp_path, monkeypatch, capsys, case, expected):
    monkeypatch.chdir(tmp_path)
    fixture = tmp_path / "catalog.json"
    if case == "bad_json":
        _write(fixture, '{"assets": [')
    elif case == "no_name":
        _write(fixture, '{"assets": [{"urn": "urn:li:dataset:x", "fields": []}]}')
    assert _audit("--config", _fixture_cfg(tmp_path, fixture)) == 1
    err = capsys.readouterr().err.strip().splitlines()[-1]
    assert err.startswith("airgap: error: ")
    assert expected in err
    assert not (tmp_path / "outputs").exists()


def test_invalid_yaml_config_is_a_readable_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cfg = _write(tmp_path / "bad.yaml", "source: [fixture\n")
    assert _audit("--config", cfg) == 1
    err = capsys.readouterr().err
    assert err.startswith(f"airgap: error: config file {cfg} is not valid YAML:")
    assert len(err.strip().splitlines()) == 1


def test_out_pointing_at_a_file_is_a_readable_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    target = _write(tmp_path / "a_file", "")
    assert _audit("--out", target) == 1
    assert "airgap: error: cannot use --out" in capsys.readouterr().err


def test_failing_datahub_lite_command_is_a_readable_error(tmp_path, monkeypatch, capsys):
    fake = tmp_path / "datahub"
    _write(fake, "#!/bin/sh\necho 'noise' >&2\necho 'IO Error: database does not exist' >&2\nexit 1\n")
    fake.chmod(0o755)
    cfg = _write(tmp_path / "cfg.yaml", f"source: datahub-lite\ndatahub_lite:\n  bin: {fake}\n")
    monkeypatch.chdir(tmp_path)
    assert _audit("--config", cfg) == 1
    err = capsys.readouterr().err
    assert err.strip().splitlines()[-1] == (
        "airgap: error: `datahub lite list-urns` failed (exit 1): "
        "IO Error: database does not exist"
    )


class _Resp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (401, "returned HTTP 401: check the token"),
        (500, "returned HTTP 500"),
        ("down", "cannot reach DataHub at http://gms.invalid:8080/api/graphql: ConnectionError"),
    ],
)
def test_gms_http_and_connection_errors_are_readable(monkeypatch, capsys, tmp_path, outcome, expected):
    import requests

    def post(self, *a, **kw):
        if outcome == "down":
            raise requests.exceptions.ConnectionError("refused")
        return _Resp(outcome)

    monkeypatch.setattr(requests.Session, "post", post)
    monkeypatch.chdir(tmp_path)
    assert _audit("--source", "datahub", "--url", "http://gms.invalid:8080") == 1
    err = capsys.readouterr().err
    assert err.startswith("airgap: error: DataHub at" if outcome != "down" else "airgap: error: cannot")
    assert expected in err
