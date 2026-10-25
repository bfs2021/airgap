"""Scenario tests from the v0.1.0 QA campaign.

Each test builds a small DataHub-shaped catalog, runs the real source and rules,
and checks the outcome. Tests marked ``xfail(strict=True)`` pin known bugs: they
start to XPASS (and fail the run) once the bug is fixed, so remove the marker then.
"""
from __future__ import annotations

import json
import os

import pytest
import yaml

from airgap.detect import run_rules
from airgap.detect.findings import Severity
from airgap.model import MetadataGraph
from airgap.report.graph_html import write_graph_html
from airgap.sources import FixtureSource
from airgap.sources.datahub import DataHubSource

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg(**detection) -> dict:
    with open(os.path.join(_ROOT, "config.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["detection"].update(detection)
    return cfg


def _urn(name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:snowflake,{name},PROD)"


class Cat:
    """Minimal fixture-catalog builder."""

    def __init__(self) -> None:
        self.assets: list[dict] = []
        self.edges: list[dict] = []
        self.field_edges: list[dict] = []

    def ds(self, name, fields=(), tags=(), owned=True) -> str:
        u = _urn(name)
        self.assets.append({
            "urn": u, "name": name, "entity_type": "dataset", "platform": "snowflake",
            "tags": list(tags), "owners": ["urn:li:corpGroup:data-eng"] if owned else [],
            "fields": [{"path": p, "native_type": "varchar", "tags": list(t)} for p, t in fields],
        })
        return u

    def dashboard(self, name) -> str:
        u = f"urn:li:dashboard:(looker,{name})"
        self.assets.append({"urn": u, "name": name, "entity_type": "dashboard",
                            "platform": "looker", "owners": ["urn:li:corpuser:bi"]})
        return u

    def edge(self, up, down):
        if {"upstream": up, "downstream": down} not in self.edges:
            self.edges.append({"upstream": up, "downstream": down})

    def col(self, up, down, field):
        self.field_edges.append({"up_urn": up, "up_field": field, "down_urn": down, "down_field": field})
        self.edge(up, down)

    def graph(self, tmp_path, assets=None) -> MetadataGraph:
        p = tmp_path / "catalog.json"
        p.write_text(json.dumps({"assets": self.assets if assets is None else assets,
                                 "edges": self.edges, "field_edges": self.field_edges},
                                ensure_ascii=False), encoding="utf-8")
        return FixtureSource(str(p)).fetch()


def _summary(findings):
    return sorted((f.rule, f.asset_name, f.severity, f.blast_radius) for f in findings)


# --------------------------------------------------------------------- passing behaviour

def test_lin01_linear_chain_severity_ladder(tmp_path):
    c = Cat()
    names = "ABCDEF"
    urns = [c.ds(n, [("email", ["PII"] if n == "A" else [])]) for n in names]
    for up, down in zip(urns, urns[1:]):
        c.col(up, down, "email")
    got = {f.asset_name: (f.severity, f.blast_radius) for f in run_rules(c.graph(tmp_path), _cfg())}
    assert got == {
        "B": (Severity.CRITICAL, 4), "C": (Severity.CRITICAL, 3), "D": (Severity.HIGH, 2),
        "E": (Severity.HIGH, 1), "F": (Severity.MEDIUM, 0),
    }


def test_dashboard_downstream_makes_leak_critical(tmp_path):
    c = Cat()
    a = c.ds("users", [("email", ["PII"])])
    b = c.ds("export", [("email", [])])
    c.col(a, b, "email")
    c.edge(b, c.dashboard("growth"))
    (f,) = run_rules(c.graph(tmp_path), _cfg())
    assert (f.rule, f.asset_name, f.severity) == ("R1", "export", Severity.CRITICAL)


def test_tagged_downstream_and_dataset_marker_are_not_leaks(tmp_path):
    c = Cat()
    a = c.ds("users", [("email", ["PII"])])
    c.col(a, c.ds("tagged", [("email", ["PII"])]), "email")
    c.col(a, c.ds("ds_marked", [("email", [])], tags=["PII"]), "email")
    assert run_rules(c.graph(tmp_path), _cfg()) == []


def test_r2_ownerless_sensitive_dataset(tmp_path):
    c = Cat()
    c.ds("hr", [("tckn", ["PII"])], owned=False)
    assert _summary(run_rules(c.graph(tmp_path), _cfg())) == [("R2", "hr", Severity.MEDIUM, 0)]


def test_r1_has_no_dataset_level_fallback(tmp_path):
    """B05: R1 walks only column-level lineage, as docs/DOCUMENTATION.md says.

    A dataset-level edge alone does not produce an R1 finding.
    """
    c = Cat()
    a = c.ds("users", [("email", ["PII"])])
    b = c.ds("users_export", [("email", [])])
    c.edge(a, b)
    assert run_rules(c.graph(tmp_path), _cfg()) == []


def test_long_chain_upstream_first_is_fine(tmp_path):
    c = Cat()
    urns = [c.ds(f"t{i}", [("x", [])]) for i in range(1500)]
    for up, down in zip(urns, urns[1:]):
        c.edge(up, down)
    g = c.graph(tmp_path)
    write_graph_html([], g, "fixture", str(tmp_path / "g.html"))
    assert (tmp_path / "g.html").exists()


def _fake_gms(monkeypatch, src: DataHubSource, datasets: dict, lineage: dict):
    def gql(query, variables):
        if "search(" in query:
            return {"search": {"total": len(datasets),
                               "searchResults": [{"entity": {"urn": u}} for u in datasets]}}
        if "dataset(" in query:
            return {"dataset": datasets[variables["urn"]]}
        rels = [{"entity": {"urn": u, "type": t}} for u, t in lineage.get(variables["urn"], [])]
        return {"entity": {"lineage": {"relationships": rels}}}
    monkeypatch.setattr(src, "_gql", gql)


def _gms_dataset(name, fields, owners=(), tags=(), fgl=None):
    tag = lambda t, props: {"tag": {"urn": f"urn:li:tag:{t}", "properties": props(t)}}
    return {
        "urn": _urn(name), "name": name, "platform": {"name": "snowflake"},
        "tags": {"tags": [tag(t, lambda _: None) for t in tags]},
        "ownership": {"owners": [{"owner": {"urn": o}} for o in owners]},
        "schemaMetadata": {"fields": [
            {"fieldPath": p, "nativeDataType": "varchar",
             "globalTags": {"tags": [tag(t, lambda _: None) for t in ts]}, "glossaryTerms": None}
            for p, ts in fields]},
        "fineGrainedLineages": fgl or [],
    }


def test_gms_tag_without_properties_uses_urn_name(monkeypatch):
    """Regression for #3 (fixed in PR #9): properties is null when the aspect is absent."""
    src = DataHubSource("http://gms.invalid", "")
    d = _gms_dataset("users", [("email", ["PII"])])
    _fake_gms(monkeypatch, src, {d["urn"]: d}, {})
    assert _summary(run_rules(src.fetch(), _cfg())) == [("R2", "users", Severity.MEDIUM, 0)]


# --------------------------------------------------------------------- known bugs (xfail)

@pytest.mark.xfail(strict=True, reason="B01: GMS SchemaFieldRef.path is the bare field path, but "
                   "_fetch_dataset expects a schemaField URN and never requests SchemaFieldRef.urn")
def test_gms_column_lineage_is_loaded(monkeypatch):
    src = DataHubSource("http://gms.invalid", "")
    up = _gms_dataset("users", [("email", ["PII"])], owners=["urn:li:corpuser:a"])
    fgl = [{"upstreams": [{"urn": up["urn"], "path": "email"}],
            "downstreams": [{"urn": _urn("export"), "path": "email"}]}]
    down = _gms_dataset("export", [("email", [])], owners=["urn:li:corpuser:a"], fgl=fgl)
    _fake_gms(monkeypatch, src, {up["urn"]: up, down["urn"]: down}, {up["urn"]: [(down["urn"], "DATASET")]})
    assert [f.asset_name for f in run_rules(src.fetch(), _cfg()) if f.rule == "R1"] == ["export"]


@pytest.mark.xfail(strict=True, reason="B02: the GMS source searches DATASET only and never loads "
                   "dashboards/charts, so human-facing consumers never raise severity")
def test_gms_dashboard_consumer_is_loaded(monkeypatch):
    src = DataHubSource("http://gms.invalid", "")
    d = _gms_dataset("users", [("email", ["PII"])])
    dash = "urn:li:dashboard:(looker,growth)"
    _fake_gms(monkeypatch, src, {d["urn"]: d}, {d["urn"]: [(dash, "DASHBOARD")]})
    g = src.fetch()
    assert g.get(dash) is not None


@pytest.mark.xfail(strict=True, reason="B04: _sensitive_origins finds no origin when every sensitive "
                   "field sits in a tagged cycle (reverse ETL), so downstream leaks are missed")
def test_leak_downstream_of_tagged_cycle(tmp_path):
    c = Cat()
    crm = c.ds("crm_users", [("email", ["PII"])])
    wh = c.ds("warehouse_users", [("email", ["PII"])])
    mk = c.ds("marketing_export", [("email", [])])
    c.col(crm, wh, "email")
    c.col(wh, crm, "email")
    c.col(wh, mk, "email")
    c.edge(mk, c.dashboard("growth"))
    assert [f.asset_name for f in run_rules(c.graph(tmp_path), _cfg())] == ["marketing_export"]


@pytest.mark.xfail(strict=True, reason="B07: a config without a detection block is not merged with "
                   "defaults, so no PII markers apply and the audit silently looks clean")
def test_config_without_detection_block_uses_defaults(tmp_path):
    c = Cat()
    c.ds("hr", [("tckn", ["PII"])], owned=False)
    assert run_rules(c.graph(tmp_path), {"source": "fixture"}) != []


@pytest.mark.xfail(strict=True, reason="B08: str.lower() maps Turkish 'İ' to 'i' + U+0307, so "
                   "'KİŞİSEL' does not match the marker 'Kişisel'")
def test_turkish_dotted_capital_i_matches(tmp_path):
    c = Cat()
    a = c.ds("kaynak", [("tc", ["Kişisel"])])
    c.col(a, c.ds("hedef", [("tc", ["KİŞİSEL"])]), "tc")
    c.col(a, c.ds("sizinti", [("tc", [])]), "tc")
    found = [f.asset_name for f in run_rules(c.graph(tmp_path), _cfg(pii_markers=["PII", "Kişisel"]))]
    assert found == ["sizinti"]


@pytest.mark.xfail(strict=True, reason="B09: a duplicate URN silently replaces the earlier asset "
                   "(add_asset overwrites), dropping its PII classification")
def test_duplicate_urn_keeps_classification(tmp_path):
    c = Cat()
    a = c.ds("users", [("email", ["PII"])])
    c.ds("users", [("email", [])])
    c.col(a, c.ds("export", [("email", [])]), "email")
    assert [f.asset_name for f in run_rules(c.graph(tmp_path), _cfg())] == ["export"]


@pytest.mark.xfail(strict=True, raises=ValueError,
                   reason="B10: write_graph_html calls max() on empty layers for an empty catalog")
def test_empty_catalog_renders_graph(tmp_path):
    g = Cat().graph(tmp_path)
    write_graph_html([], g, "fixture", str(tmp_path / "g.html"))


@pytest.mark.xfail(strict=True, raises=RecursionError,
                   reason="B11: graph_html._depths recurses ~3 frames per hop; a chain listed "
                   "downstream-first overflows above 332 nodes (498 on 3.12)")
def test_long_chain_downstream_first_renders_graph(tmp_path):
    c = Cat()
    urns = [c.ds(f"t{i}", [("x", [])]) for i in range(600)]
    for up, down in zip(urns, urns[1:]):
        c.edge(up, down)
    g = c.graph(tmp_path, assets=c.assets[::-1])
    write_graph_html([], g, "fixture", str(tmp_path / "g.html"))


@pytest.mark.xfail(strict=True, reason="B15: transitive_downstream counts the asset itself inside a "
                   "cycle, contradicting its docstring ('excluding itself') and inflating severity")
def test_cycle_blast_radius_excludes_self(tmp_path):
    c = Cat()
    a = c.ds("A", [("email", ["PII"])])
    b = c.ds("B", [("email", [])])
    cc = c.ds("C", [("email", [])])
    c.col(a, b, "email")
    c.col(b, cc, "email")
    c.col(cc, a, "email")
    assert {f.asset_name: f.blast_radius for f in run_rules(c.graph(tmp_path), _cfg())} == {"B": 2, "C": 2}
