"""Unit tests for the DataHub Lite source helpers (issue #8).

The catalog is fed in as the ``{urn: {aspect: value}}`` mapping that
``DataHubLiteSource._read_docs`` produces, so no ``datahub`` binary, DuckDB or
subprocess is involved.
"""
from __future__ import annotations

import pytest

from airgap.model import MetadataGraph
from airgap.sources.datahub_lite import (
    DataHubLiteFormatError,
    DataHubLiteSource,
    _as_urn,
    _docs_from_export,
    _entity_type,
    _platform,
)

USERS = "urn:li:dataset:(urn:li:dataPlatform:postgres,app.users,PROD)"
MART = "urn:li:dataset:(urn:li:dataPlatform:snowflake,wh.mart,PROD)"
ORDERS = "urn:li:dataset:(urn:li:dataPlatform:postgres,app.orders,PROD)"
DASH = "urn:li:dashboard:(looker,sales)"
CHART = "urn:li:chart:(looker,sales_chart)"


# ── small pure helpers ──────────────────────────────────────────────────────


def test_entity_type_and_platform_come_from_the_urn():
    assert _entity_type(USERS) == "dataset"
    assert _entity_type(DASH) == "dashboard"
    assert _platform(USERS, "dataset") == "postgres"
    assert _platform(DASH, "dashboard") == "looker"
    assert _platform("urn:li:chart:(looker,sales_chart)", "chart") == "looker"


def test_as_urn_reads_every_serialization_the_aspect_uses():
    assert _as_urn(USERS) == USERS
    assert _as_urn({"string": USERS}) == USERS
    assert _as_urn({"destinationUrn": USERS}) == USERS
    assert _as_urn({"urn": USERS}) == USERS
    assert _as_urn(7) == ""
    assert _as_urn({}) == ""


# ── export parsing ──────────────────────────────────────────────────────────


def _mcp(urn: str, aspect: str, value: dict) -> dict:
    return {"entityUrn": urn, "aspectName": aspect, "aspect": {"json": value}}


def test_docs_from_export_groups_aspects_by_urn():
    docs = _docs_from_export(
        [_mcp(USERS, "datasetProperties", {"name": "users"}), _mcp(USERS, "ownership", {})]
    )
    assert docs == {
        USERS: {"datasetProperties": {"name": "users"}, "ownership": {}},
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"not": "a list"},
        [1],
        [{"entityUrn": "nope", "aspectName": "datasetProperties", "aspect": {"json": {}}}],
        [{"entityUrn": USERS, "aspectName": "", "aspect": {"json": {}}}],
        [{"entityUrn": USERS, "aspectName": "datasetProperties", "aspect": {"json": []}}],
        [{"entityUrn": USERS, "aspectName": "datasetProperties"}],
    ],
    ids=["not-a-list", "item-not-object", "urn-missing-prefix", "no-aspect-name",
         "aspect-json-not-object", "no-aspect"],
)
def test_docs_from_export_rejects_an_unexpected_format(payload):
    with pytest.raises(DataHubLiteFormatError, match="unexpected format"):
        _docs_from_export(payload)


def test_read_docs_falls_back_to_list_urns_and_get(monkeypatch):
    src = DataHubLiteSource()
    monkeypatch.setattr(src, "_export", lambda: None)
    monkeypatch.setattr(src, "_list_urns", lambda: [USERS])
    monkeypatch.setattr(src, "_get", lambda urn: {"datasetProperties": {"name": urn}})

    assert src._read_docs() == {USERS: {"datasetProperties": {"name": USERS}}}


# ── aspect mapping ──────────────────────────────────────────────────────────


def test_to_dataset_keeps_urn_only_tags_and_glossary_terms():
    doc = {
        "datasetProperties": {"name": "app.users"},
        "globalTags": {"tags": [{"tag": "urn:li:tag:Email"}]},
        "ownership": {"owners": [{"owner": "urn:li:corpuser:dpo"}]},
        "schemaMetadata": {
            "fields": [
                {
                    "fieldPath": "email",
                    "nativeDataType": "varchar",
                    "globalTags": {"tags": [{"tag": "urn:li:tag:PII"}]},
                    "glossaryTerms": {"terms": [{"urn": "urn:li:glossaryTerm:Sensitive"}]},
                }
            ]
        },
    }

    asset = DataHubLiteSource()._to_dataset(USERS, doc)

    assert asset.name == "app.users"
    assert asset.platform == "postgres"
    assert asset.tags == ("Email",)
    assert asset.owners == ("urn:li:corpuser:dpo",)
    assert [(f.path, f.native_type, f.tags, f.glossary_terms) for f in asset.fields] == [
        ("email", "varchar", ("PII",), ("Sensitive",))
    ]


def test_to_consumer_reads_the_title_and_platform():
    asset = DataHubLiteSource()._to_consumer(DASH, {"dashboardInfo": {"title": "Sales"}}, "dashboard")
    assert (asset.entity_type, asset.name, asset.platform) == ("dashboard", "Sales", "looker")


def test_consumer_lineage_accepts_string_and_union_urns():
    graph = MetadataGraph()
    doc = {
        "dashboardInfo": {
            "datasets": [USERS, {"string": MART}, {"destinationUrn": ORDERS}]
        }
    }

    DataHubLiteSource()._add_consumer_lineage(graph, DASH, doc, "dashboard")

    assert [(e.upstream, e.downstream) for e in graph.edges] == [
        (USERS, DASH),
        (MART, DASH),
        (ORDERS, DASH),
    ]


def test_chart_inputs_accept_destination_urn_objects():
    graph = MetadataGraph()
    doc = {"chartInfo": {"inputs": [{"destinationUrn": USERS}]}}

    DataHubLiteSource()._add_consumer_lineage(graph, CHART, doc, "chart")

    assert [(e.upstream, e.downstream) for e in graph.edges] == [(USERS, CHART)]


def test_dataset_lineage_reads_upstreams_and_fine_grained_refs():
    graph = MetadataGraph()
    doc = {
        "upstreamLineage": {
            "upstreams": [{"dataset": MART}],
            "fineGrainedLineages": [
                {
                    "upstreams": [f"urn:li:schemaField:({MART},email)"],
                    "downstreams": [f"urn:li:schemaField:({USERS},email)"],
                }
            ],
        }
    }

    DataHubLiteSource()._add_dataset_lineage(graph, USERS, doc)

    assert [(e.upstream, e.downstream) for e in graph.edges] == [(MART, USERS)]
    assert [(e.up_urn, e.up_field, e.down_urn, e.down_field) for e in graph.field_edges] == [
        (MART, "email", USERS, "email")
    ]


def test_fetch_builds_assets_and_edges_from_the_docs(monkeypatch):
    docs = {
        USERS: {"datasetProperties": {"name": "app.users"}},
        MART: {"datasetProperties": {"name": "mart"}},
        DASH: {"dashboardInfo": {"title": "Sales", "datasets": [{"string": MART}]}},
    }
    src = DataHubLiteSource()
    monkeypatch.setattr(src, "_read_docs", lambda: docs)

    graph = src.fetch()

    assert set(graph.assets) == {USERS, MART, DASH}
    assert graph.get(DASH).entity_type == "dashboard"
    assert graph.get(DASH).name == "Sales"
    assert [(e.upstream, e.downstream) for e in graph.edges] == [(MART, DASH)]
