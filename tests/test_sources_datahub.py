"""Unit tests for the GMS source helpers (issue #8).

Synthetic GraphQL payloads in the shape DataHub returns; ``requests.Session.post``
is replaced, so the tests need neither network access nor a DataHub install.
"""
from __future__ import annotations

from airgap.sources.datahub import DataHubSource, _split_schema_field, _tag_names

USERS = "urn:li:dataset:(urn:li:dataPlatform:postgres,app.users,PROD)"
ORDERS = "urn:li:dataset:(urn:li:dataPlatform:postgres,app.orders,PROD)"
MART = "urn:li:dataset:(urn:li:dataPlatform:snowflake,wh.mart,PROD)"


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeGMS:
    """Answers the search / dataset / lineage queries and logs every call."""

    def __init__(self, datasets: dict, lineage: dict | None = None) -> None:
        self.datasets = datasets
        self.lineage = lineage or {}
        self.search_calls: list[tuple[int, int]] = []
        self.dataset_calls: list[str] = []

    def post(self, url, json=None, timeout=None):
        query, v = json["query"], json["variables"]
        if "search(" in query:
            self.search_calls.append((v["start"], v["count"]))
            urns = list(self.datasets)
            page = urns[v["start"] : v["start"] + v["count"]]
            data = {
                "search": {
                    "total": len(urns),
                    "searchResults": [{"entity": {"urn": u}} for u in page],
                }
            }
        elif "dataset(urn:" in query:
            self.dataset_calls.append(v["urn"])
            data = {"dataset": self.datasets[v["urn"]]}
        elif "lineage(" in query:
            targets = self.lineage.get(v["urn"], [])
            page = targets[v["start"] : v["start"] + v["count"]]
            data = {
                "entity": {
                    "lineage": {
                        "start": v["start"],
                        "count": len(page),
                        "total": len(targets),
                        "relationships": [
                            {"type": "DownstreamOf", "entity": {"urn": u, "type": "DATASET"}}
                            for u in page
                        ],
                    }
                }
            }
        else:  # pragma: no cover - a new query needs a new fake
            raise AssertionError(f"unexpected query: {query}")
        return _Resp({"data": data})


def _source(gms: FakeGMS, **kwargs) -> DataHubSource:
    src = DataHubSource(url="http://gms.invalid:8080", token="", **kwargs)
    src._session.post = gms.post
    return src


# ── _tag_names ───────────────────────────────────────────────────────────────


def test_tag_names_falls_back_to_the_urn_when_a_tag_has_no_properties():
    # issue #3: older or SDK-created tags carry only the URN.
    container = {
        "tags": [
            {"tag": {"urn": "urn:li:tag:PII"}},
            {"tag": {"urn": "urn:li:tag:Email", "properties": {"name": "Email Address"}}},
        ]
    }
    assert _tag_names(container, "tags") == ("PII", "Email Address")


def test_tag_names_reads_glossary_terms():
    container = {"terms": [{"term": {"urn": "urn:li:glossaryTerm:Classification.Sensitive"}}]}
    assert _tag_names(container, "terms") == ("Classification.Sensitive",)


def test_tag_names_handles_missing_containers_and_empty_names():
    assert _tag_names(None, "tags") == ()
    assert _tag_names({}, "tags") == ()
    assert _tag_names({"tags": [{"tag": {}}]}, "tags") == ()


# ── _split_schema_field ──────────────────────────────────────────────────────


def test_split_schema_field_returns_the_dataset_urn_and_field_path():
    ref = f"urn:li:schemaField:({USERS},email)"
    assert _split_schema_field(ref) == (USERS, "email")


def test_split_schema_field_leaves_a_plain_path_alone():
    assert _split_schema_field("email") == ("", "email")


# ── search paging ───────────────────────────────────────────────────────────


def test_list_dataset_urns_walks_every_search_page():
    datasets = {u: {} for u in (USERS, ORDERS, MART)}
    gms = FakeGMS(datasets)
    src = _source(gms, page_size=2)

    assert src._list_dataset_urns() == [USERS, ORDERS, MART]
    assert gms.search_calls == [(0, 2), (2, 2)]  # 3 results, 2 per page


def test_list_dataset_urns_stops_when_a_page_is_empty():
    calls: list[int] = []

    def post(url, json=None, timeout=None):
        start = json["variables"]["start"]
        calls.append(start)
        results = [{"entity": {"urn": USERS}}] if start == 0 else []
        # A total that overstates the results must not loop forever.
        return _Resp({"data": {"search": {"total": 9, "searchResults": results}}})

    src = _source(FakeGMS({}), page_size=2)
    src._session.post = post

    assert src._list_dataset_urns() == [USERS]
    assert calls == [0, 2]


# ── _fetch_dataset ──────────────────────────────────────────────────────────


def _dataset_payload() -> dict:
    return {
        "urn": USERS,
        "name": "app.users",
        "platform": {"name": "postgres"},
        "tags": {"tags": [{"tag": {"urn": "urn:li:tag:Email"}}]},
        "ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:dpo"}}]},
        "schemaMetadata": {
            "fields": [
                {
                    "fieldPath": "email",
                    "nativeDataType": "varchar",
                    "globalTags": {"tags": [{"tag": {"urn": "urn:li:tag:PII"}}]},
                    "glossaryTerms": {
                        "terms": [
                            {"term": {"urn": "urn:li:glossaryTerm:Classification.Sensitive"}}
                        ]
                    },
                }
            ]
        },
        "fineGrainedLineages": [
            {
                "upstreams": [{"urn": USERS, "path": "email"}],
                "downstreams": [{"urn": MART, "path": "email"}],
            },
            {
                # SchemaField URNs instead of urn/path pairs take the fallback path.
                "upstreams": [{"urn": f"urn:li:schemaField:({MART},email)"}],
                "downstreams": [{"urn": f"urn:li:schemaField:({ORDERS},email)"}],
            },
        ],
    }


def test_fetch_dataset_keeps_urn_only_tags_and_field_metadata():
    gms = FakeGMS({USERS: _dataset_payload()})
    asset, field_edges = _source(gms)._fetch_dataset(USERS)

    assert asset.urn == USERS
    assert asset.platform == "postgres"
    assert asset.tags == ("Email",)
    assert asset.owners == ("urn:li:corpuser:dpo",)
    assert [(f.path, f.native_type, f.tags, f.glossary_terms) for f in asset.fields] == [
        ("email", "varchar", ("PII",), ("Classification.Sensitive",))
    ]
    assert [(e.up_urn, e.up_field, e.down_urn, e.down_field) for e in field_edges] == [
        (USERS, "email", MART, "email"),
        (MART, "email", ORDERS, "email"),
    ]
    assert gms.dataset_calls == [USERS]


def test_fetch_dataset_falls_back_to_the_requested_urn_when_the_payload_omits_it():
    payload = _dataset_payload()
    del payload["urn"]
    del payload["name"]
    gms = FakeGMS({USERS: payload})

    asset, _ = _source(gms)._fetch_dataset(USERS)

    assert asset.urn == USERS
    assert asset.name == USERS


# ── downstream paging ───────────────────────────────────────────────────────


def test_downstream_pages_through_a_long_lineage_list():
    targets = [ORDERS, MART, "urn:li:dashboard:(looker,sales)"]
    gms = FakeGMS({USERS: {}}, {USERS: targets})
    src = _source(gms, lineage_page_size=2)

    assert [e["urn"] for e in src._downstream(USERS)] == targets
