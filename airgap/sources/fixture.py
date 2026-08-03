"""Load a synthetic DataHub-shape metadata graph from a JSON fixture.

The fixture uses the exact same field names and lineage model as real DataHub
metadata, so the detection engine cannot tell the difference between this and a
live instance.
"""
from __future__ import annotations

import json

from airgap.model import Asset, Field, FieldLineage, LineageEdge, MetadataGraph
from airgap.sources.base import MetadataSource


class FixtureSource(MetadataSource):
    name = "fixture"

    def __init__(self, path: str) -> None:
        self.path = path

    def fetch(self) -> MetadataGraph:
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)

        graph = MetadataGraph()
        for a in raw.get("assets", []):
            fields = tuple(
                Field(
                    path=f["path"],
                    native_type=f.get("native_type", ""),
                    tags=tuple(f.get("tags", [])),
                    glossary_terms=tuple(f.get("glossary_terms", [])),
                )
                for f in a.get("fields", [])
            )
            graph.add_asset(
                Asset(
                    urn=a["urn"],
                    name=a["name"],
                    entity_type=a.get("entity_type", "dataset"),
                    platform=a.get("platform", ""),
                    tags=tuple(a.get("tags", [])),
                    owners=tuple(a.get("owners", [])),
                    fields=fields,
                )
            )

        graph.edges = [
            LineageEdge(upstream=e["upstream"], downstream=e["downstream"])
            for e in raw.get("edges", [])
        ]
        graph.field_edges = [
            FieldLineage(
                up_urn=fe["up_urn"],
                up_field=fe["up_field"],
                down_urn=fe["down_urn"],
                down_field=fe["down_field"],
            )
            for fe in raw.get("field_edges", [])
        ]
        return graph
