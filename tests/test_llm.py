"""A failed local LLM must not put its error text into the report (#29)."""
from __future__ import annotations

from airgap import cli
from airgap.detect.findings import Finding
from airgap.llm import LocalLLM


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


def _raise_generate(self, prompt):
    raise RuntimeError("HTTP Error 500: Internal Server Error")


def test_enrich_returns_no_prose_when_generate_fails(monkeypatch):
    monkeypatch.setattr(LocalLLM, "_generate", _raise_generate)

    assert LocalLLM().enrich(_finding()) == ""


def test_cli_warns_once_and_leaves_explanations_empty(monkeypatch, capsys):
    monkeypatch.setattr(LocalLLM, "available", lambda self: True)
    monkeypatch.setattr(LocalLLM, "_generate", _raise_generate)
    findings = [_finding("AIRGAP-R1-001"), _finding("AIRGAP-R2-001")]

    cli._enrich_with_llm(findings, {"ollama": {}})

    captured = capsys.readouterr()
    assert [f.explanation for f in findings] == ["", ""]
    assert captured.err.count("!") == 1
    assert "could not explain 2 finding(s)" in captured.err
    assert "Internal Server Error" not in captured.err
    assert "unavailable" not in captured.out + captured.err


def test_cli_keeps_prose_when_the_model_answers(monkeypatch, capsys):
    monkeypatch.setattr(LocalLLM, "available", lambda self: True)
    monkeypatch.setattr(LocalLLM, "_generate", lambda self, prompt: "Leaked PII.")

    findings = [_finding()]
    cli._enrich_with_llm(findings, {"ollama": {}})

    assert findings[0].explanation == "Leaked PII."
    assert "!" not in capsys.readouterr().err
