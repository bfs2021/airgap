"""Column-level lineage from the DataHub GMS GraphQL source (issue #2).

The payloads below are synthetic but follow the shape of DataHub's GraphQL
schema: ``FineGrainedLineage.upstreams/downstreams`` are ``SchemaFieldRef``
objects whose ``urn`` is the dataset URN and whose ``path`` is the bare field
path (see ``FineGrainedLineagesMapper`` in datahub-graphql-core).
No network access is needed: ``requests.Session.post`` is replaced.
"""
import os

import yaml

from airgap.detect import run_rules
from airgap.model import FieldLineage
from airgap.sources.datahub import DataHubSource, _field_ref

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

USERS = "urn:li:dataset:(urn:li:dataPlatform:postgres,acme.public.users,PROD)"
MKT = "urn:li:dataset:(urn:li:dataPlatform:snowflake,acme.marketing.enriched,PROD)"


def _schema_field(dataset_urn: str, path: str) -> str:
    return f"urn:li:schemaField:({dataset_urn},{path})"


def _tag(name: str) -> dict:
    return {"tag": {"urn": f"urn:li:tag:{name}", "properties": {"name": name}}}


def _field(path: str, tags=()) -> dict:
    return {
        "fieldPath": path,
        "nativeDataType": "varchar",
        "globalTags": {"tags": [_tag(t) for t in tags]} if tags else None,
        "glossaryTerms": None,
    }


DATASETS = {
    USERS: {
        "urn": USERS,
        "name": "acme.public.users",
        "platform": {"name": "postgres"},
        "tags": None,
        "ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:dpo"}}]},
        "schemaMetadata": {
            "fields": [_field("id"), _field("email", ["PII"]), _field("name", ["PII"])]
        },
        "fineGrainedLineages": [],
    },
    MKT: {
        "urn": MKT,
        "name": "acme.marketing.enriched",
        "platform": {"name": "snowflake"},
        "tags": None,
        "ownership": {"owners": [{"owner": {"urn": "urn:li:corpGroup:marketing"}}]},
        "schemaMetadata": {"fields": [_field("user_id"), _field("email"), _field("name")]},
        # Real GMS shape: urn = dataset URN, path = bare field path.
        "fineGrainedLineages": [
            {
                "upstreams": [{"urn": USERS, "path": "email"}],
                "downstreams": [{"urn": MKT, "path": "email"}],
            },
            {
                "upstreams": [{"urn": USERS, "path": "name"}],
                "downstreams": [{"urn": MKT, "path": "name"}],
            },
            {
                "upstreams": [{"urn": USERS, "path": "id"}],
                "downstreams": [{"urn": MKT, "path": "user_id"}],
            },
        ],
    },
}

LINEAGE = {USERS: [MKT], MKT: []}


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _fake_post(datasets=DATASETS, lineage=LINEAGE):
    def post(url, json=None, timeout=None):  # noqa: A002 (mirrors requests)
        query, variables = json["query"], json["variables"]
        if "search(" in query:
            urns = list(datasets)
            start, count = variables["start"], variables["count"]
            page = urns[start : start + count]
            data = {
                "search": {
                    "total": len(urns),
                    "searchResults": [{"entity": {"urn": u}} for u in page],
                }
            }
        elif "dataset(urn:" in query:
            data = {"dataset": datasets[variables["urn"]]}
        elif "lineage(" in query:
            rels = [
                {"type": "DownstreamOf", "entity": {"urn": u, "type": "DATASET"}}
                for u in lineage.get(variables["urn"], [])
            ]
            data = {"entity": {"lineage": {"relationships": rels}}}
        else:  # pragma: no cover - a new query would need a new fake
            raise AssertionError(f"unexpected query: {query}")
        return _Resp({"data": data})

    return post


def _source(**kwargs) -> DataHubSource:
    src = DataHubSource(url="http://gms.invalid:8080", token="")
    src._session.post = _fake_post(**kwargs)
    return src


def _cfg() -> dict:
    with open(os.path.join(_ROOT, "config.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_field_ref_uses_dataset_urn_and_bare_path():
    assert _field_ref({"urn": USERS, "path": "email"}) == (USERS, "email")


def test_field_ref_falls_back_to_schema_field_urn():
    full = _schema_field(USERS, "email")
    assert _field_ref({"urn": full, "path": "email"}) == (USERS, "email")
    assert _field_ref({"urn": "", "path": full}) == (USERS, "email")


def test_field_ref_incomplete_values():
    assert _field_ref(None) == ("", "")
    assert _field_ref({"urn": None, "path": "email"}) == ("", "email")


def test_fetch_dataset_builds_field_lineage_from_schema_field_refs():
    _asset, edges = _source()._fetch_dataset(MKT)
    assert edges == [
        FieldLineage(USERS, "email", MKT, "email"),
        FieldLineage(USERS, "name", MKT, "name"),
        FieldLineage(USERS, "id", MKT, "user_id"),
    ]


def test_fetch_dataset_accepts_full_schema_field_urns():
    mkt = dict(DATASETS[MKT])
    mkt["fineGrainedLineages"] = [
        {
            "upstreams": [{"urn": _schema_field(USERS, "email"), "path": "email"}],
            "downstreams": [{"urn": _schema_field(MKT, "email"), "path": "email"}],
        }
    ]
    src = _source(datasets={USERS: DATASETS[USERS], MKT: mkt})
    _asset, edges = src._fetch_dataset(MKT)
    assert edges == [FieldLineage(USERS, "email", MKT, "email")]


def test_fetch_dataset_skips_refs_without_dataset_urn():
    mkt = dict(DATASETS[MKT])
    mkt["fineGrainedLineages"] = [
        {"upstreams": [{"urn": "", "path": "email"}], "downstreams": [{"urn": MKT, "path": "email"}]}
    ]
    src = _source(datasets={USERS: DATASETS[USERS], MKT: mkt})
    assert src._fetch_dataset(MKT)[1] == []


def test_r1_fires_on_gms_column_lineage():
    graph = _source().fetch()
    assert len(graph.field_edges) == 3
    r1 = [f for f in run_rules(graph, _cfg()) if f.rule == "R1"]
    assert len(r1) == 1
    assert r1[0].asset_urn == MKT
    assert r1[0].leaked_fields == ["email", "name"]
    assert any("acme.public.users.email" in ev for ev in r1[0].evidence)
