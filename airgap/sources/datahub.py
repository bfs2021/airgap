"""Live DataHub metadata source (GraphQL).

Reads real schema, tags, glossary terms, ownership and lineage from any DataHub
instance via its GraphQL API and normalizes it into the same `MetadataGraph`
the fixture produces. Point it at a live instance with `--url` / `--token`.

Only read-only queries are issued. This module is the "genuine integration"
path; the bundled fixture mirrors exactly the shape it returns.
"""
from __future__ import annotations

from typing import Any

import requests

from airgap.model import Asset, Field, FieldLineage, LineageEdge, MetadataGraph
from airgap.sources.base import MetadataSource

_SEARCH = """
query search($start: Int!, $count: Int!) {
  search(input: {type: DATASET, query: "*", start: $start, count: $count}) {
    total
    searchResults { entity { urn } }
  }
}
"""

_DATASET = """
query dataset($urn: String!) {
  dataset(urn: $urn) {
    urn
    name
    platform { name }
    tags { tags { tag { urn properties { name } } } }
    ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
    schemaMetadata {
      fields {
        fieldPath
        nativeDataType
        globalTags { tags { tag { urn properties { name } } } }
        glossaryTerms { terms { term { urn properties { name } } } }
      }
    }
    fineGrainedLineages { upstreams { urn path } downstreams { urn path } }
  }
}
"""

_LINEAGE = """
query lineage($urn: String!, $dir: LineageDirection!) {
  entity(urn: $urn) {
    ... on Dataset {
      lineage(input: {direction: $dir, start: 0, count: 200}) {
        relationships { entity { urn type } }
      }
    }
  }
}
"""


def _short(urn: str) -> str:
    """Extract the simple tag or term identifier from a DataHub URN."""
    return urn.rsplit(":", 1)[-1] if urn else ""


def _tag_names(container: dict | None, key: str) -> tuple[str, ...]:
    if not container:
        return ()
    out: list[str] = []
    for item in container.get(key, []) or []:
        node = item.get("tag") or item.get("term") or {}
        props = node.get("properties") or {}
        raw = props.get("name")
        if not raw:
            urn = node.get("urn", "")
            name = _short(urn)
        else:
            name = raw
        if name:
            out.append(name)
    return tuple(out)


class DataHubSource(MetadataSource):
    name = "datahub"

    def __init__(self, url: str, token: str, lineage_depth: int = 4, page_size: int = 50) -> None:
        if not url:
            raise ValueError("datahub.url is required for source=datahub")
        self.endpoint = url.rstrip("/") + "/api/graphql"
        self.token = token
        self.lineage_depth = lineage_depth
        self.page_size = page_size
        self._session = requests.Session()
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"
        self._session.headers["Content-Type"] = "application/json"

    def _gql(self, query: str, variables: dict[str, Any]) -> dict:
        resp = self._session.post(
            self.endpoint, json={"query": query, "variables": variables}, timeout=60
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"DataHub GraphQL error: {payload['errors']}")
        return payload.get("data", {}) or {}

    def _list_dataset_urns(self) -> list[str]:
        urns: list[str] = []
        start = 0
        while True:
            data = self._gql(_SEARCH, {"start": start, "count": self.page_size})
            block = data.get("search") or {}
            results = block.get("searchResults") or []
            for r in results:
                ent = r.get("entity") or {}
                if ent.get("urn"):
                    urns.append(ent["urn"])
            start += self.page_size
            if start >= (block.get("total") or 0) or not results:
                break
        return urns

    def _fetch_dataset(self, urn: str) -> tuple[Asset, list[FieldLineage]]:
        data = self._gql(_DATASET, {"urn": urn})
        d = data.get("dataset") or {}
        platform = ((d.get("platform") or {}).get("name")) or ""
        tags = _tag_names(d.get("tags"), "tags")
        owners = tuple(
            (o.get("owner") or {}).get("urn", "")
            for o in ((d.get("ownership") or {}).get("owners") or [])
            if (o.get("owner") or {}).get("urn")
        )
        fields: list[Field] = []
        for f in ((d.get("schemaMetadata") or {}).get("fields") or []):
            fields.append(
                Field(
                    path=f.get("fieldPath", ""),
                    native_type=f.get("nativeDataType", ""),
                    tags=_tag_names(f.get("globalTags"), "tags"),
                    glossary_terms=_tag_names(f.get("glossaryTerms"), "terms"),
                )
            )
        asset = Asset(
            urn=d.get("urn", urn),
            name=d.get("name", urn),
            entity_type="dataset",
            platform=platform,
            tags=tags,
            owners=owners,
            fields=tuple(fields),
        )
        # Column-level lineage. Each upstream/downstream is a SchemaFieldRef.
        field_edges: list[FieldLineage] = []
        for fg in (d.get("fineGrainedLineages") or []):
            for up in (fg.get("upstreams") or []):
                for down in (fg.get("downstreams") or []):
                    up_urn, up_field = _field_ref(up)
                    down_urn, down_field = _field_ref(down)
                    if up_urn and down_urn and up_field and down_field:
                        field_edges.append(
                            FieldLineage(up_urn, up_field, down_urn, down_field)
                        )
        return asset, field_edges

    def _fetch_edges(self, urn: str) -> list[LineageEdge]:
        data = self._gql(_LINEAGE, {"urn": urn, "dir": "DOWNSTREAM"})
        rels = (((data.get("entity") or {}).get("lineage") or {}).get("relationships")) or []
        edges: list[LineageEdge] = []
        for r in rels:
            ent = r.get("entity") or {}
            if ent.get("urn"):
                edges.append(LineageEdge(upstream=urn, downstream=ent["urn"]))
        return edges

    def fetch(self) -> MetadataGraph:
        graph = MetadataGraph()
        urns = self._list_dataset_urns()
        for urn in urns:
            asset, field_edges = self._fetch_dataset(urn)
            graph.add_asset(asset)
            graph.field_edges.extend(field_edges)
        for urn in urns:
            graph.edges.extend(self._fetch_edges(urn))
        return graph


def _field_ref(ref: dict | None) -> tuple[str, str]:
    """Turn a GraphQL ``SchemaFieldRef`` into (dataset_urn, field_path).

    DataHub's ``FineGrainedLineagesMapper`` fills ``urn`` with the dataset URN
    and ``path`` with the bare field path, so those are used as they are. If
    either value is a full ``urn:li:schemaField:(...)`` URN instead, it is split
    with ``_split_schema_field`` as a fallback.
    """
    ref = ref or {}
    urn = ref.get("urn") or ""
    path = ref.get("path") or ""
    for candidate in (urn, path):
        if candidate.startswith("urn:li:schemaField:"):
            return _split_schema_field(candidate)
    return urn, path


def _split_schema_field(path: str) -> tuple[str, str]:
    """Split a DataHub schemaField URN into (dataset_urn, field_path).

    Example:
      urn:li:schemaField:(urn:li:dataset:(...),email) -> ((urn:li:dataset:(...)), email)
    """
    if not path.startswith("urn:li:schemaField:"):
        return "", path
    inner = path[len("urn:li:schemaField:") :].strip("()")
    # inner looks like: urn:li:dataset:(...),fieldPath
    idx = inner.rfind(",")
    if idx == -1:
        return "", path
    return inner[:idx], inner[idx + 1 :]
