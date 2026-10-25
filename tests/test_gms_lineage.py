"""GMS lineage: consumer assets, lineage_depth and paging (issue #4).

Synthetic GraphQL payloads in the shape of DataHub's schema
(``EntityLineageResult { start count total relationships { type entity } }``).
No network access is needed: ``requests.Session.post`` is replaced.
"""
import os

import yaml

from airgap.detect import run_rules
from airgap.detect.findings import Severity
from airgap.sources.datahub import DataHubSource

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ds(name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:snowflake,{name},PROD)"


RAW = _ds("acme.raw.users")
MART = _ds("acme.mart.users")
CHART = "urn:li:chart:(looker,acme.users_chart)"
DASH = "urn:li:dashboard:(looker,acme.users_dashboard)"
JOB = "urn:li:dataJob:(urn:li:dataFlow:(airflow,etl,PROD),copy_users)"

_OWNED = {"owners": [{"owner": {"urn": "urn:li:corpuser:dpo"}}]}


def _dataset(urn: str, pii: bool = False, owned: bool = True) -> dict:
    tag = {"tag": {"urn": "urn:li:tag:PII", "properties": {"name": "PII"}}}
    return {
        "urn": urn,
        "name": urn.split(",")[1],
        "platform": {"name": "snowflake"},
        "tags": None,
        "ownership": _OWNED if owned else None,
        "schemaMetadata": {
            "fields": [
                {
                    "fieldPath": "email",
                    "nativeDataType": "varchar",
                    "globalTags": {"tags": [tag]} if pii else None,
                    "glossaryTerms": None,
                }
            ]
        },
        "fineGrainedLineages": [],
    }


def _entity(urn: str) -> dict:
    """Lineage target as GMS returns it for the inline fragments we ask for."""
    etype = urn.split(":")[2]
    if etype == "dataset":
        return {"urn": urn, "type": "DATASET"}
    if etype == "dataJob":
        return {"urn": urn, "type": "DATA_JOB", "properties": {"name": "copy_users"}, "ownership": None}
    return {
        "urn": urn,
        "type": etype.upper(),
        "platform": {"name": "looker"},
        "properties": {"name": urn.split(",")[1].rstrip(")")},
        "ownership": _OWNED,
    }


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeGMS:
    """Answers the three airgap queries from in-memory data and logs calls."""

    def __init__(self, datasets: dict, lineage: dict) -> None:
        self.datasets = datasets
        self.lineage = lineage
        self.lineage_calls: list[tuple[str, int, int]] = []

    def post(self, url, json=None, timeout=None):  # noqa: A002 (mirrors requests)
        query, v = json["query"], json["variables"]
        if "search(" in query:
            urns = list(self.datasets)
            page = urns[v["start"] : v["start"] + v["count"]]
            data = {
                "search": {
                    "total": len(urns),
                    "searchResults": [{"entity": {"urn": u}} for u in page],
                }
            }
        elif "dataset(urn:" in query:
            data = {"dataset": self.datasets[v["urn"]]}
        elif "lineage(" in query:
            assert v["dir"] == "DOWNSTREAM"
            self.lineage_calls.append((v["urn"], v["start"], v["count"]))
            targets = self.lineage.get(v["urn"], [])
            page = targets[v["start"] : v["start"] + v["count"]]
            data = {
                "entity": {
                    "lineage": {
                        "start": v["start"],
                        "count": len(page),
                        "total": len(targets),
                        "relationships": [
                            {"type": "DownstreamOf", "degree": 1, "entity": _entity(u)}
                            for u in page
                        ],
                    }
                }
            }
        else:  # pragma: no cover - a new query would need a new fake
            raise AssertionError(f"unexpected query: {query}")
        return _Resp({"data": data})


def _source(gms: FakeGMS, **kwargs) -> DataHubSource:
    src = DataHubSource(url="http://gms.invalid:8080", token="", **kwargs)
    src._session.post = gms.post
    return src


def _cfg() -> dict:
    with open(os.path.join(_ROOT, "config.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_dashboards_and_charts_are_loaded_as_assets():
    gms = FakeGMS({RAW: _dataset(RAW)}, {RAW: [CHART, DASH]})
    graph = _source(gms).fetch()
    assert graph.get(CHART).entity_type == "chart"
    assert graph.get(DASH).entity_type == "dashboard"
    assert graph.get(DASH).name == "acme.users_dashboard"
    assert graph.get(DASH).platform == "looker"
    assert graph.get(DASH).owners == ("urn:li:corpuser:dpo",)
    assert graph.consumers_by_type(graph.transitive_downstream(RAW)) == {
        "chart": 1,
        "dashboard": 1,
    }
    # Consumers are not datasets, so the rules do not treat them as such.
    assert [a.urn for a in graph.datasets()] == [RAW]


def test_pii_feeding_a_dashboard_is_critical():
    # An ownerless dataset with classified PII, consumed by one dashboard.
    # Blast radius is 1; the dashboard makes it CRITICAL (human-facing).
    gms = FakeGMS({RAW: _dataset(RAW, pii=True, owned=False)}, {RAW: [DASH]})
    findings = run_rules(_source(gms).fetch(), _cfg())
    assert len(findings) == 1
    assert findings[0].rule == "R2"
    assert findings[0].consumers == {"dashboard": 1}
    assert findings[0].severity == Severity.CRITICAL


def test_r1_leak_into_a_dataset_feeding_a_dashboard_is_critical():
    # raw.email is classified PII; mart.email receives it through column
    # lineage without a classification, and a dashboard reads mart.
    # The column refs are full schemaField URNs, which the source splits in
    # both the current and the urn/path form of the query (see issue #2).
    mart = _dataset(MART)
    mart["fineGrainedLineages"] = [
        {
            "upstreams": [{"path": f"urn:li:schemaField:({RAW},email)"}],
            "downstreams": [{"path": f"urn:li:schemaField:({MART},email)"}],
        }
    ]
    gms = FakeGMS({RAW: _dataset(RAW, pii=True), MART: mart}, {RAW: [MART], MART: [DASH]})
    findings = run_rules(_source(gms).fetch(), _cfg())
    assert [(f.rule, f.asset_urn) for f in findings] == [("R1", MART)]
    assert findings[0].leaked_fields == ["email"]
    assert findings[0].consumers == {"dashboard": 1}
    assert findings[0].severity == Severity.CRITICAL


def test_lineage_depth_limits_hops_past_datasets():
    datasets = {RAW: _dataset(RAW)}
    lineage = {RAW: [CHART], CHART: [DASH]}

    shallow = _source(FakeGMS(datasets, lineage), lineage_depth=1).fetch()
    assert CHART in shallow.assets
    assert DASH not in shallow.assets
    assert shallow.transitive_downstream(RAW) == {CHART}

    deep = _source(FakeGMS(datasets, lineage), lineage_depth=2).fetch()
    assert deep.transitive_downstream(RAW) == {CHART, DASH}
    assert deep.consumers_by_type({CHART, DASH}) == {"chart": 1, "dashboard": 1}


def test_lineage_depth_below_one_is_treated_as_one():
    gms = FakeGMS({RAW: _dataset(RAW)}, {RAW: [CHART], CHART: [DASH]})
    graph = _source(gms, lineage_depth=0).fetch()
    assert graph.transitive_downstream(RAW) == {CHART}


def test_multi_hop_through_a_data_job():
    # raw -> job -> mart: the job's downstream is followed, so mart is
    # reachable from raw even without a direct raw -> mart edge.
    gms = FakeGMS(
        {RAW: _dataset(RAW), MART: _dataset(MART)},
        {RAW: [JOB], JOB: [MART], MART: [DASH]},
    )
    graph = _source(gms).fetch()
    assert graph.get(JOB).entity_type == "dataJob"
    assert graph.transitive_downstream(RAW) == {JOB, MART, DASH}
    # Each entity is asked for its downstream lineage once.
    asked = [u for u, _s, _c in gms.lineage_calls]
    assert sorted(asked) == sorted([RAW, MART, JOB, DASH])


def test_lineage_pages_past_200_results():
    many = [f"urn:li:chart:(looker,c{i})" for i in range(450)]
    gms = FakeGMS({RAW: _dataset(RAW)}, {RAW: many})
    graph = _source(gms, lineage_depth=1).fetch()
    assert [(s, c) for u, s, c in gms.lineage_calls if u == RAW] == [
        (0, 200),
        (200, 200),
        (400, 200),
    ]
    assert len(graph.edges) == 450
    assert graph.consumers_by_type(graph.transitive_downstream(RAW)) == {"chart": 450}


def test_cycles_terminate_and_edges_are_not_duplicated():
    gms = FakeGMS(
        {RAW: _dataset(RAW), MART: _dataset(MART)},
        {RAW: [MART], MART: [RAW]},
    )
    graph = _source(gms).fetch()
    assert sorted((e.upstream, e.downstream) for e in graph.edges) == sorted(
        [(RAW, MART), (MART, RAW)]
    )
