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
    return FixtureSource(os.path.join(_ROOT, "airgap", "data", "acme_datalake.json")).fetch()


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


def test_null_properties_tag_and_term_recognized_as_pii():
    """Verify that tags and glossary terms without properties.name (properties: null)

    have their URN prefix stripped and are properly matched against pii_markers.
    """
    from airgap.detect.findings import is_sensitive, normalize_markers
    from airgap.sources.datahub import _tag_names

    pii_set = normalize_markers(_cfg()["detection"]["pii_markers"])

    # Tag urn:li:tag:PII with properties: null (properties: None)
    tag_container = {"tags": [{"tag": {"urn": "urn:li:tag:PII", "properties": None}}]}
    tags = _tag_names(tag_container, "tags")
    assert tags == ("PII",)
    assert is_sensitive(tags, pii_set) is True

    # Glossary term urn:li:glossaryTerm:Email with properties: null
    term_container = {"terms": [{"term": {"urn": "urn:li:glossaryTerm:Email", "properties": None}}]}
    terms = _tag_names(term_container, "terms")
    assert terms == ("Email",)
    assert is_sensitive(terms, pii_set) is True


def test_marker_matching_folds_case_including_turkish_i():
    from airgap.detect.findings import is_sensitive, normalize_markers

    pii_set = normalize_markers(["Kişisel", "Kısıtlı", "Classification.Sensitive", "PII"])
    for tag in ("KİŞİSEL", "kişisel", "KISITLI", "kısıtlı", "SENSITIVE", "pii",
                "Ki\u0307şi\u0307sel", "Kis\u0327isel"):
        assert is_sensitive([tag], pii_set), tag
    assert not is_sensitive(["Kamu", "Public"], pii_set)
