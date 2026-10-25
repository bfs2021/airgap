"""Versioned findings.json, SARIF output, --format and --fail-on (issue #6)."""
import json
import os
import re

import pytest

from airgap import __version__, cli
from airgap.detect.findings import Severity

_SCHEMA = os.path.join(os.path.dirname(__file__), "data", "sarif-schema-2.1.0.json")


def _audit(out, *argv: str) -> int:
    return cli.main(["audit", "--no-llm", "--out", str(out), *argv])


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sarif_validator():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _load(_SCHEMA)
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def test_findings_json_keys_are_pinned(tmp_path):
    assert _audit(tmp_path) == 0
    data = _load(tmp_path / "findings.json")
    assert list(data) == [
        "schema_version",
        "airgap_version",
        "generated_at",
        "source",
        "findings",
    ]
    assert data["schema_version"] == 1
    assert data["airgap_version"] == __version__
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["generated_at"])
    assert data["source"] == "fixture"
    assert list(data["findings"][0]) == [
        "id",
        "rule",
        "title",
        "severity",
        "asset_urn",
        "asset_name",
        "leaked_fields",
        "evidence",
        "blast_radius",
        "consumers",
        "remediation",
        "explanation",
    ]


def test_default_formats_are_unchanged(tmp_path):
    assert _audit(tmp_path) == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["findings.json", "lineage_graph.html", "patches", "report.md"]


def test_format_is_repeatable_and_limits_outputs(tmp_path):
    assert _audit(tmp_path, "--format", "sarif", "--format", "md") == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["findings.sarif", "patches", "report.md"]


def test_sarif_validates_against_the_2_1_0_schema(tmp_path):
    validator = _sarif_validator()
    assert _audit(tmp_path, "--format", "sarif") == 0
    doc = _load(tmp_path / "findings.sarif")
    errors = [e.message for e in validator.iter_errors(doc)]
    assert errors == []
    assert doc["version"] == "2.1.0"


def test_sarif_schema_check_rejects_a_broken_log(tmp_path):
    # Guards against a validator that accepts anything.
    validator = _sarif_validator()
    assert _audit(tmp_path, "--format", "sarif") == 0
    doc = _load(tmp_path / "findings.sarif")
    doc["runs"][0]["results"][0]["level"] = "critical"
    assert list(validator.iter_errors(doc))


def test_sarif_maps_rules_severity_and_asset(tmp_path):
    assert _audit(tmp_path, "--format", "sarif", "--format", "json") == 0
    findings = _load(tmp_path / "findings.json")["findings"]
    run = _load(tmp_path / "findings.sarif")["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "airgap"
    assert driver["version"] == __version__
    assert [r["id"] for r in driver["rules"]] == ["R1", "R2"]

    results = run["results"]
    assert len(results) == len(findings) == 5
    level = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning"}
    for f, r in zip(findings, results):
        assert r["ruleId"] == f["rule"]
        assert driver["rules"][r["ruleIndex"]]["id"] == f["rule"]
        assert r["level"] == level[f["severity"]]
        assert r["properties"]["severity"] == f["severity"]
        assert r["properties"]["id"] == f["id"]
        (loc,) = r["locations"][0]["logicalLocations"]
        assert loc == {"name": f["asset_name"], "fullyQualifiedName": f["asset_urn"]}
    prints = [r["partialFingerprints"]["airgapFinding/v1"] for r in results]
    assert len(set(prints)) == len(prints)


def test_fail_on_high_exits_2_on_acme(tmp_path):
    assert _audit(tmp_path, "--fail-on", "high") == 2


def test_fail_on_critical_alias_still_works(tmp_path):
    assert _audit(tmp_path, "--fail-on-critical") == 2
    assert _audit(tmp_path) == 0


@pytest.mark.parametrize(
    "keep, threshold, code",
    [
        ({Severity.HIGH, Severity.MEDIUM}, "critical", 0),
        ({Severity.HIGH, Severity.MEDIUM}, "high", 2),
        ({Severity.MEDIUM}, "high", 0),
        ({Severity.MEDIUM}, "medium", 2),
    ],
)
def test_fail_on_threshold(tmp_path, monkeypatch, keep, threshold, code):
    real = cli.run_rules

    def only(graph, cfg):
        return [f for f in real(graph, cfg) if f.severity in keep]

    monkeypatch.setattr(cli, "run_rules", only)
    assert _audit(tmp_path, "--fail-on", threshold) == code
