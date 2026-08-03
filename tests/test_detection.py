"""Detection regression tests against the bundled Acme fixture."""
import os

import yaml

from airgap.detect import run_rules
from airgap.detect.findings import Severity
from airgap.sources import FixtureSource

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg() -> dict:
    with open(os.path.join(_ROOT, "config.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _graph():
    return FixtureSource(os.path.join(_ROOT, "fixtures", "acme_datalake.json")).fetch()


def _by_asset(findings):
    out: dict[str, list] = {}
    for f in findings:
        out.setdefault(f.asset_name, []).append(f)
    return out


def test_finding_count_and_severity_spectrum():
    findings = run_rules(_graph(), _cfg())
    assert len(findings) == 5
    sev = [f.severity for f in findings]
    assert sev.count(Severity.CRITICAL) == 3
    assert sev.count(Severity.HIGH) == 1
    assert sev.count(Severity.MEDIUM) == 1


def test_marketing_enriched_flagged_by_both_rules():
    by_asset = _by_asset(run_rules(_graph(), _cfg()))
    rules = {f.rule for f in by_asset["acme.marketing.marketing_enriched"]}
    assert rules == {"R1", "R2"}


def test_r1_reports_leaked_fields_with_full_lineage_path():
    by_asset = _by_asset(run_rules(_graph(), _cfg()))
    r1 = next(
        f
        for f in by_asset["acme.marketing.marketing_enriched"]
        if f.rule == "R1"
    )
    assert set(r1.leaked_fields) == {"email", "name"}
    # The evidence must trace back to the true PII source (postgres users).
    assert any("acme.public.users.email" in ev for ev in r1.evidence)


def test_internal_only_leak_is_medium():
    by_asset = _by_asset(run_rules(_graph(), _cfg()))
    f = by_asset["acme.analytics.tmp_user_export"][0]
    assert f.severity == Severity.MEDIUM
    assert f.blast_radius == 0


def test_properly_governed_assets_are_not_flagged():
    names = {f.asset_name for f in run_rules(_graph(), _cfg())}
    # dim_customer is fully tagged + owned; retention_calc carries a dataset PII
    # tag; neither should be reported.
    assert "acme.analytics.dim_customer" not in names
    assert "acme.analytics.retention_calc" not in names
