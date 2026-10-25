"""DataHub Lite metadata source.

Reads real DataHub metadata aspects from a local DataHub Lite instance (a
DuckDB-backed DataHub that needs no Docker and no cloud). This is the genuine,
fully-local DataHub integration: metadata is ingested into DataHub Lite via the
official SDK, then read back here through the `datahub lite` CLI and normalized
into the same MetadataGraph the fixture and live-GMS sources produce.

DataHub Lite embodies Airgap's whole thesis: a local-first governance auditor
reading from a local-first DataHub. Nothing leaves the machine.

The catalog is read with one public `datahub lite export` call. If that command
fails, Airgap falls back to `datahub lite list-urns` plus one `datahub lite get`
per entity, which gives the same result but starts one process per entity. An
export that succeeds but has an unexpected format is an error, never an empty
catalog. Only the public `datahub` CLI is used, no DataHub Python internals.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from airgap.errors import AirgapError
from airgap.model import Asset, Field, FieldLineage, LineageEdge, MetadataGraph
from airgap.sources.base import MetadataSource
from airgap.sources.datahub import _split_schema_field


def _urn_name(urn: str) -> str:
    return urn.split(":", 1)[-1]


def _short(urn: str) -> str:
    tag = urn.rsplit(":", 1)[-1]
    return tag


def _entity_type(urn: str) -> str:
    # urn:li:dataset:(...) / urn:li:dashboard:(...) / urn:li:chart:(...)
    parts = urn.split(":")
    return parts[2] if len(parts) > 2 else "dataset"


def _platform(urn: str, etype: str) -> str:
    if etype == "dataset":
        marker = "dataPlatform:"
        if marker in urn:
            after = urn.split(marker, 1)[1]
            return after.split(",", 1)[0]
        return ""
    # dashboard/chart urn: urn:li:dashboard:(looker,acme.x)
    inner = urn.split("(", 1)[1] if "(" in urn else ""
    return inner.split(",", 1)[0] if inner else ""


def _as_urn(item) -> str:
    """DataHub serializes urn arrays sometimes as strings, sometimes as
    union objects like {"string": "urn:..."} or edges {"destinationUrn": ...}."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("string") or item.get("destinationUrn") or item.get("urn") or ""
    return ""


class DataHubLiteFormatError(AirgapError, ValueError):
    """`datahub lite export` succeeded but its output is not in the expected format.

    An AirgapError, so the CLI prints it as a one-line `airgap: error:` message.
    """


def _format_error(detail: str) -> DataHubLiteFormatError:
    return DataHubLiteFormatError(
        f"`datahub lite export` returned an unexpected format ({detail}); this "
        "DataHub version may not be supported. Airgap stopped instead of "
        "reporting an empty or partial catalog."
    )


def _docs_from_export(payload) -> dict[str, dict]:
    """Group exported aspects into {urn: {aspectName: aspect}}, like `get` returns.

    The export is a JSON list of metadata change proposals, each with
    `entityUrn`, `aspectName` and the aspect value under `aspect.json`.
    Anything else raises DataHubLiteFormatError.
    """
    if not isinstance(payload, list):
        raise _format_error(f"expected a JSON list, got {type(payload).__name__}")
    docs: dict[str, dict] = {}
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            raise _format_error(f"item {i} is a {type(item).__name__}, not an object")
        urn, aspect_name = item.get("entityUrn"), item.get("aspectName")
        aspect = item.get("aspect")
        value = aspect.get("json") if isinstance(aspect, dict) else None
        if not isinstance(urn, str) or not urn.startswith("urn:li:"):
            raise _format_error(f"item {i} has no string 'entityUrn'")
        if not isinstance(aspect_name, str) or not aspect_name:
            raise _format_error(f"item {i} has no string 'aspectName'")
        if not isinstance(value, dict):
            raise _format_error(f"item {i} has no object at 'aspect.json'")
        docs.setdefault(urn, {})[aspect_name] = value
    return docs


def _names(assoc: dict | None, key: str, id_field: str) -> tuple[str, ...]:
    if not assoc:
        return ()
    out: list[str] = []
    for item in assoc.get(key, []) or []:
        raw = item.get(id_field, "")
        if raw:
            out.append(_short(raw))  # urn:li:tag:PII -> PII
    return tuple(out)


class DataHubLiteSource(MetadataSource):
    name = "datahub-lite"

    def __init__(self, datahub_bin: str | None = None) -> None:
        self.datahub_bin = datahub_bin or self._default_bin()

    @staticmethod
    def _default_bin() -> str:
        candidate = os.path.join(os.path.dirname(sys.executable), "datahub")
        return candidate if os.path.exists(candidate) else "datahub"

    def _run(self, *args: str) -> str:
        env = dict(os.environ, PYTHONWARNINGS="ignore")
        try:
            proc = subprocess.run(
                [self.datahub_bin, "lite", *args],
                capture_output=True,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            raise AirgapError(
                f"DataHub CLI not found: {self.datahub_bin!r}. Install it with "
                'pip install "airgap-datahub[datahub-lite]", or set datahub_lite.bin '
                "in the config file to the path of the datahub executable."
            ) from None
        if proc.returncode != 0:
            lines = [ln.strip() for ln in proc.stderr.splitlines() if ln.strip()]
            raise AirgapError(
                f"`datahub lite {' '.join(args)}` failed (exit {proc.returncode}): "
                f"{lines[-1] if lines else 'no error output'}"
            )
        return proc.stdout

    def _list_urns(self) -> list[str]:
        out = self._run("list-urns")
        return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("urn:li:")]

    def _get(self, urn: str) -> dict:
        return json.loads(self._run("get", "--urn", urn))

    def _export(self) -> str | None:
        """Raw `datahub lite export` output, or None when the command fails."""
        fd, path = tempfile.mkstemp(prefix="airgap-lite-export-", suffix=".json")
        os.close(fd)
        try:
            try:
                self._run("export", "--file", path)
            except Exception as exc:  # noqa: BLE001  the export command itself failed
                lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip()]
                detail = " ".join(lines[:1] + lines[1:][-1:]) or "export failed"
                print(
                    f"  ! {detail}; reading entities one by one instead (slower).",
                    file=sys.stderr,
                )
                return None
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        finally:
            os.unlink(path)

    def _read_docs(self) -> dict[str, dict]:
        raw = self._export()
        if raw is None:
            return {urn: self._get(urn) for urn in self._list_urns()}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _format_error(f"not valid JSON: {exc}") from None
        docs = _docs_from_export(payload)
        if not docs and self._list_urns():
            raise _format_error("no entities, but `datahub lite list-urns` lists some")
        return docs

    def fetch(self) -> MetadataGraph:
        graph = MetadataGraph()
        docs = self._read_docs()

        for urn, doc in docs.items():
            etype = _entity_type(urn)
            if etype == "dataset":
                graph.add_asset(self._to_dataset(urn, doc))
            else:
                graph.add_asset(self._to_consumer(urn, doc, etype))

        # Lineage edges from every dataset's upstreamLineage + consumer inputs.
        for urn, doc in docs.items():
            etype = _entity_type(urn)
            if etype == "dataset":
                self._add_dataset_lineage(graph, urn, doc)
            else:
                self._add_consumer_lineage(graph, urn, doc, etype)
        return graph

    def _to_dataset(self, urn: str, doc: dict) -> Asset:
        props = doc.get("datasetProperties") or {}
        schema = doc.get("schemaMetadata") or {}
        fields = tuple(
            Field(
                path=f.get("fieldPath", ""),
                native_type=f.get("nativeDataType", ""),
                tags=_names(f.get("globalTags"), "tags", "tag"),
                glossary_terms=_names(f.get("glossaryTerms"), "terms", "urn"),
            )
            for f in schema.get("fields", [])
        )
        owners = tuple(
            o.get("owner", "")
            for o in ((doc.get("ownership") or {}).get("owners") or [])
            if o.get("owner")
        )
        return Asset(
            urn=urn,
            name=props.get("name") or _urn_name(urn),
            entity_type="dataset",
            platform=_platform(urn, "dataset"),
            tags=_names(doc.get("globalTags"), "tags", "tag"),
            owners=owners,
            fields=fields,
        )

    def _to_consumer(self, urn: str, doc: dict, etype: str) -> Asset:
        info = doc.get("dashboardInfo") or doc.get("chartInfo") or {}
        owners = tuple(
            o.get("owner", "")
            for o in ((doc.get("ownership") or {}).get("owners") or [])
            if o.get("owner")
        )
        return Asset(
            urn=urn,
            name=info.get("title") or _urn_name(urn),
            entity_type=etype,
            platform=_platform(urn, etype),
            owners=owners,
        )

    def _add_dataset_lineage(self, graph: MetadataGraph, urn: str, doc: dict) -> None:
        up = doc.get("upstreamLineage") or {}
        for u in up.get("upstreams", []) or []:
            ds = u.get("dataset")
            if ds:
                graph.edges.append(LineageEdge(upstream=ds, downstream=urn))
        for fg in up.get("fineGrainedLineages", []) or []:
            ups = fg.get("upstreams") or []
            downs = fg.get("downstreams") or []
            for uf in ups:
                up_urn, up_field = _split_schema_field(uf)
                for df in downs:
                    down_urn, down_field = _split_schema_field(df)
                    if up_urn and down_urn:
                        graph.field_edges.append(
                            FieldLineage(up_urn, up_field, down_urn, down_field)
                        )

    def _add_consumer_lineage(
        self, graph: MetadataGraph, urn: str, doc: dict, etype: str
    ) -> None:
        info = doc.get("dashboardInfo") or doc.get("chartInfo") or {}
        consumed = info.get("datasets") or info.get("inputs") or []
        for ds in consumed:
            ds_urn = _as_urn(ds)
            if ds_urn:
                graph.edges.append(LineageEdge(upstream=ds_urn, downstream=urn))
