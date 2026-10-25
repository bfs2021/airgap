"""Live DataHub metadata source (GraphQL).

Reads real schema, tags, glossary terms, ownership and lineage from any DataHub
instance via its GraphQL API and normalizes it into the same `MetadataGraph`
the fixture produces. Point it at a live instance with `--url` / `--token`.

Only read-only queries are issued. This module is the "genuine integration"
path; the bundled fixture mirrors exactly the shape it returns.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import requests

from airgap.errors import AirgapError
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

_OWNERS = "ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }"

# One hop of downstream lineage for any entity that has a lineage graph
# (datasets, charts, dashboards, data jobs, ML models, ...), one page at a
# time. Non-dataset targets carry enough metadata to become assets.
_LINEAGE = (
    """
query lineage($urn: String!, $dir: LineageDirection!, $start: Int!, $count: Int!) {
  entity(urn: $urn) {
    ... on EntityWithRelationships {
      lineage(input: {direction: $dir, start: $start, count: $count}) {
        start
        count
        total
        relationships {
          type
          entity {
            urn
            type
            ... on Dashboard { platform { name } properties { name } OWNERS }
            ... on Chart { platform { name } properties { name } OWNERS }
            ... on DataJob { properties { name } OWNERS }
            ... on DataFlow { platform { name } properties { name } OWNERS }
            ... on MLModel { name platform { name } OWNERS }
            ... on MLModelGroup { name platform { name } OWNERS }
          }
        }
      }
    }
  }
}
"""
).replace("OWNERS", _OWNERS)


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


def _entity_type(urn: str) -> str:
    """Entity type from a URN, e.g. urn:li:dashboard:(...) -> dashboard.

    Uses the same spelling as the DataHub Lite source (dataset, dashboard,
    chart, mlModel, dataJob, ...), which is what ``human_facing_types`` in
    the config refers to.
    """
    parts = urn.split(":")
    return parts[2] if len(parts) > 2 and parts[0] == "urn" else "dataset"


def _owner_urns(entity: dict) -> tuple[str, ...]:
    return tuple(
        (o.get("owner") or {}).get("urn", "")
        for o in ((entity.get("ownership") or {}).get("owners") or [])
        if (o.get("owner") or {}).get("urn")
    )


def _consumer_asset(entity: dict) -> Asset:
    """Build an Asset for a non-dataset lineage target (dashboard, chart, ...)."""
    urn = entity["urn"]
    name = (
        ((entity.get("properties") or {}).get("name"))
        or entity.get("name")
        or urn
    )
    return Asset(
        urn=urn,
        name=name,
        entity_type=_entity_type(urn),
        platform=((entity.get("platform") or {}).get("name")) or "",
        owners=_owner_urns(entity),
    )


class DataHubSource(MetadataSource):
    name = "datahub"

    def __init__(
        self,
        url: str,
        token: str,
        lineage_depth: int = 4,
        page_size: int = 50,
        lineage_page_size: int = 200,
    ) -> None:
        if not url:
            raise ValueError("datahub.url is required for source=datahub")
        self.endpoint = url.rstrip("/") + "/api/graphql"
        self.token = token
        # Downstream hops walked from each dataset; at least one.
        self.lineage_depth = max(1, int(lineage_depth))
        self.page_size = page_size
        self.lineage_page_size = lineage_page_size
        self._session = requests.Session()
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"
        self._session.headers["Content-Type"] = "application/json"

    def _gql(self, query: str, variables: dict[str, Any]) -> dict:
        try:
            resp = self._session.post(
                self.endpoint, json={"query": query, "variables": variables}, timeout=60
            )
        except requests.exceptions.RequestException as exc:
            raise AirgapError(
                f"cannot reach DataHub at {self.endpoint}: {type(exc).__name__}"
            ) from None
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "error"
            hint = (
                ": check the token (--token, AIRGAP_DATAHUB_TOKEN or datahub.token)"
                if code in (401, 403)
                else ""
            )
            raise AirgapError(f"DataHub at {self.endpoint} returned HTTP {code}{hint}") from None
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

    def _downstream(self, urn: str) -> list[dict]:
        """All one-hop downstream lineage entities of ``urn``, across pages."""
        out: list[dict] = []
        start = 0
        while True:
            data = self._gql(
                _LINEAGE,
                {
                    "urn": urn,
                    "dir": "DOWNSTREAM",
                    "start": start,
                    "count": self.lineage_page_size,
                },
            )
            block = ((data.get("entity") or {}).get("lineage")) or {}
            rels = block.get("relationships") or []
            for r in rels:
                ent = r.get("entity") or {}
                if ent.get("urn"):
                    out.append(ent)
            start += self.lineage_page_size
            if not rels or start >= (block.get("total") or 0):
                break
        return out

    def _fetch_edges(self, urn: str) -> list[LineageEdge]:
        return [LineageEdge(upstream=urn, downstream=e["urn"]) for e in self._downstream(urn)]

    def _walk_lineage(self, graph: MetadataGraph, dataset_urns: list[str]) -> None:
        """Breadth-first downstream walk, at most ``lineage_depth`` hops.

        Every dataset found by search starts at hop 0. Non-dataset targets
        (dashboards, charts, data jobs, ML models, ...) are added as assets,
        and their own downstream lineage is followed while the hop count
        stays below ``lineage_depth``. So with the default of 4, a chain
        dataset -> chart -> dashboard is loaded in full, and with 1 only the
        direct consumers of each dataset are.
        """
        hops: dict[str, int] = {u: 0 for u in dataset_urns}
        queue: deque[str] = deque(dataset_urns)
        seen_edges: set[tuple[str, str]] = set()
        while queue:
            urn = queue.popleft()
            hop = hops[urn]
            for ent in self._downstream(urn):
                target = ent["urn"]
                if (urn, target) not in seen_edges:
                    seen_edges.add((urn, target))
                    graph.edges.append(LineageEdge(upstream=urn, downstream=target))
                if target not in graph.assets and _entity_type(target) != "dataset":
                    graph.add_asset(_consumer_asset(ent))
                if target not in hops:
                    hops[target] = hop + 1
                    if hop + 1 < self.lineage_depth:
                        queue.append(target)

    def fetch(self) -> MetadataGraph:
        graph = MetadataGraph()
        urns = self._list_dataset_urns()
        for urn in urns:
            asset, field_edges = self._fetch_dataset(urn)
            graph.add_asset(asset)
            graph.field_edges.extend(field_edges)
        self._walk_lineage(graph, urns)
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
