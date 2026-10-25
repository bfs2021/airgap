"""Normalized metadata model.

This is the *contract* every metadata source must produce. Whether metadata
comes from a live DataHub instance or a bundled fixture, both are normalized
into these dataclasses so the detection engine is completely source-agnostic.

The shape mirrors DataHub's own metadata model (URNs, schema fields with
tags/glossary terms, ownership, dataset- and column-level lineage).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Field:
    """A single schema field (column) on a dataset."""

    path: str
    native_type: str = ""
    tags: tuple[str, ...] = ()
    glossary_terms: tuple[str, ...] = ()

    def markers(self) -> tuple[str, ...]:
        """All governance markers on this field (tags + glossary terms)."""
        return tuple(self.tags) + tuple(self.glossary_terms)


@dataclass(frozen=True)
class Asset:
    """Any DataHub entity: dataset, dashboard, chart, mlModel, ...

    Only datasets carry `fields`; consumers like dashboards/charts have none.
    """

    urn: str
    name: str
    entity_type: str = "dataset"  # dataset | dashboard | chart | mlModel | ...
    platform: str = ""
    tags: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    fields: tuple[Field, ...] = ()

    def field_by_path(self, path: str) -> Field | None:
        for f in self.fields:
            if f.path == path:
                return f
        return None

    def all_markers(self) -> set[str]:
        """Dataset-level tags plus every field-level marker."""
        out: set[str] = set(self.tags)
        for f in self.fields:
            out.update(f.markers())
        return out


@dataclass(frozen=True)
class LineageEdge:
    """Dataset/asset-level lineage: data flows upstream -> downstream."""

    upstream: str  # urn
    downstream: str  # urn


@dataclass(frozen=True)
class FieldLineage:
    """Column-level lineage: one upstream field feeds one downstream field."""

    up_urn: str
    up_field: str
    down_urn: str
    down_field: str


@dataclass
class MetadataGraph:
    """The full normalized graph produced by a source."""

    assets: dict[str, Asset] = field(default_factory=dict)
    edges: list[LineageEdge] = field(default_factory=list)
    field_edges: list[FieldLineage] = field(default_factory=list)
    _index_key: tuple[int, int] | None = field(default=None, init=False, repr=False, compare=False)
    _index: tuple | None = field(default=None, init=False, repr=False, compare=False)

    # ---- construction ----
    def add_asset(self, asset: Asset) -> None:
        self.assets[asset.urn] = asset

    # ---- lookup ----
    def get(self, urn: str) -> Asset | None:
        return self.assets.get(urn)

    def downstream(self, urn: str) -> list[str]:
        return list(self._edge_index()[0].get(urn, ()))

    def upstream(self, urn: str) -> list[str]:
        return list(self._edge_index()[1].get(urn, ()))

    def _edge_index(self) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """Downstream and upstream adjacency built from `edges`, in edge order.

        Sources append to `edges` or assign a new list, so the index is
        rebuilt whenever the list object or its length changes. Without it
        every lookup scanned all edges, which made detection quadratic.
        """
        key = (id(self.edges), len(self.edges))
        if self._index_key != key:
            down: dict[str, list[str]] = {}
            up: dict[str, list[str]] = {}
            for e in self.edges:
                down.setdefault(e.upstream, []).append(e.downstream)
                up.setdefault(e.downstream, []).append(e.upstream)
            self._index = (down, up)
            self._index_key = key
        return self._index

    def transitive_downstream(self, urn: str) -> set[str]:
        """All assets reachable downstream from `urn` (excluding itself)."""
        down = self._edge_index()[0]
        seen: set[str] = set()
        stack = list(down.get(urn, ()))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(down.get(cur, ()))
        seen.discard(urn)  # a lineage cycle leads back to the asset itself
        return seen

    def field_downstream(self, urn: str, field_path: str) -> list[FieldLineage]:
        return [
            fe
            for fe in self.field_edges
            if fe.up_urn == urn and fe.up_field == field_path
        ]

    def consumers_by_type(self, urns: Iterable[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for u in urns:
            a = self.assets.get(u)
            if a:
                counts[a.entity_type] = counts.get(a.entity_type, 0) + 1
        return counts

    def datasets(self) -> list[Asset]:
        return [a for a in self.assets.values() if a.entity_type == "dataset"]
