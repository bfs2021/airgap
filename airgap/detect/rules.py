"""Deterministic governance-leak rules.

The detection logic is plain, testable code — the local LLM only explains the
findings later, it never decides them. This keeps results reproducible and
hallucination-free.

Rules implemented:
  R1  Untagged PII propagation — a field classified as PII/sensitive flows,
      through lineage, into a downstream field/dataset that carries no
      equivalent classification.
  R2  Ownerless sensitive asset — a dataset that holds sensitive data (directly
      or by lineage) has no owner, so nobody is accountable for it.
"""
from __future__ import annotations

from airgap.detect.findings import (
    Finding,
    is_sensitive,
    score_severity,
    sort_key,
)
from airgap.model import Asset, MetadataGraph


def _short(urn: str) -> str:
    """Human-friendly short name for an asset URN."""
    return urn.split(",")[-2] if "," in urn else urn


def _field_sensitive(asset: Asset | None, field_path: str, pii_set: set[str]) -> bool:
    if asset is None:
        return False
    fld = asset.field_by_path(field_path)
    return bool(fld and is_sensitive(fld.markers(), pii_set))


def _dataset_marked(asset: Asset | None, pii_set: set[str]) -> bool:
    return bool(asset and is_sensitive(asset.tags, pii_set))


def _sensitive_origins(graph: MetadataGraph, pii_set: set[str]) -> list[tuple[str, str]]:
    """Sensitive fields with no sensitive upstream — where PII first appears."""
    upstream: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for fe in graph.field_edges:
        upstream.setdefault((fe.down_urn, fe.down_field), []).append(
            (fe.up_urn, fe.up_field)
        )

    origins: list[tuple[str, str]] = []
    for ds in graph.datasets():
        for f in ds.fields:
            if not is_sensitive(f.markers(), pii_set):
                continue
            ups = upstream.get((ds.urn, f.path), [])
            has_sensitive_upstream = any(
                _field_sensitive(graph.get(u), fp, pii_set) for u, fp in ups
            )
            if not has_sensitive_upstream:
                origins.append((ds.urn, f.path))
    return origins


def _walk_fields(
    graph: MetadataGraph, origins: list[tuple[str, str]]
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """BFS over column-level lineage from each origin.

    Returns reached-node -> lineage path (list of (urn, field)) from its origin.
    """
    adj: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for fe in graph.field_edges:
        adj.setdefault((fe.up_urn, fe.up_field), []).append((fe.down_urn, fe.down_field))

    paths: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for origin in origins:
        queue: list[tuple[tuple[str, str], list[tuple[str, str]]]] = [(origin, [origin])]
        while queue:
            node, path = queue.pop(0)
            for nxt in adj.get(node, []):
                if nxt in paths:
                    continue
                new_path = path + [nxt]
                paths[nxt] = new_path
                queue.append((nxt, new_path))
    return paths


def _path_str(graph: MetadataGraph, path: list[tuple[str, str]]) -> str:
    parts = []
    for urn, fld in path:
        a = graph.get(urn)
        name = a.name if a else _short(urn)
        parts.append(f"{name}.{fld}")
    return " -> ".join(parts)


def _blast(graph: MetadataGraph, urn: str) -> tuple[int, dict[str, int]]:
    downstream = graph.transitive_downstream(urn)
    consumers = graph.consumers_by_type(downstream)
    return len(downstream), consumers


def rule_r1(graph: MetadataGraph, cfg: dict, pii_set: set[str]) -> list[Finding]:
    det = cfg.get("detection", {})
    human = det.get("human_facing_types", [])
    sev = det.get("severity", {})
    origins = _sensitive_origins(graph, pii_set)
    reached = _walk_fields(graph, origins)

    # Collect leaked downstream fields, grouped by the offending dataset.
    grouped: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for (urn, fld), path in reached.items():
        asset = graph.get(urn)
        if _field_sensitive(asset, fld, pii_set) or _dataset_marked(asset, pii_set):
            continue  # properly classified downstream — not a leak
        grouped.setdefault(urn, {})[fld] = path

    findings: list[Finding] = []
    idx = 0
    for urn, fields in grouped.items():
        idx += 1
        asset = graph.get(urn)
        blast, consumers = _blast(graph, urn)
        severity = score_severity(
            blast,
            consumers,
            human,
            int(sev.get("critical_blast_radius", 3)),
            int(sev.get("high_blast_radius", 1)),
        )
        evidence = [_path_str(graph, p) for p in fields.values()]
        leaked = sorted(fields.keys())
        findings.append(
            Finding(
                id=f"AIRGAP-R1-{idx:03d}",
                rule="R1",
                title=f"Untagged PII propagation into {asset.name if asset else _short(urn)}",
                severity=severity,
                asset_urn=urn,
                asset_name=asset.name if asset else _short(urn),
                leaked_fields=leaked,
                evidence=evidence,
                blast_radius=blast,
                consumers=consumers,
                remediation=(
                    f"Apply the PII/Sensitive classification (and matching glossary "
                    f"term) to field(s) {', '.join(leaked)} on "
                    f"{asset.name if asset else _short(urn)}, or mask/drop them "
                    f"before this asset. Propagate the term from the upstream "
                    f"classified column."
                ),
            )
        )
    return findings


def rule_r2(graph: MetadataGraph, cfg: dict, pii_set: set[str]) -> list[Finding]:
    det = cfg.get("detection", {})
    human = det.get("human_facing_types", [])
    sev = det.get("severity", {})

    origins = _sensitive_origins(graph, pii_set)
    tainted_urns = {u for (u, _f) in _walk_fields(graph, origins)}
    tainted_urns.update(u for (u, _f) in origins)

    findings: list[Finding] = []
    idx = 0
    for ds in graph.datasets():
        if ds.owners:
            continue
        self_sensitive = bool(ds.all_markers()) and is_sensitive(ds.all_markers(), pii_set)
        if not (self_sensitive or ds.urn in tainted_urns):
            continue
        idx += 1
        blast, consumers = _blast(graph, ds.urn)
        severity = score_severity(
            blast,
            consumers,
            human,
            int(sev.get("critical_blast_radius", 3)),
            int(sev.get("high_blast_radius", 1)),
        )
        reason = (
            "holds directly classified PII"
            if self_sensitive
            else "receives PII via lineage from an upstream classified source"
        )
        findings.append(
            Finding(
                id=f"AIRGAP-R2-{idx:03d}",
                rule="R2",
                title=f"Ownerless sensitive asset: {ds.name}",
                severity=severity,
                asset_urn=ds.urn,
                asset_name=ds.name,
                leaked_fields=[],
                evidence=[f"{ds.name} {reason} but has no assigned owner."],
                blast_radius=blast,
                consumers=consumers,
                remediation=(
                    f"Assign an accountable owner (team or user) to {ds.name} in "
                    f"DataHub, and confirm a retention/data-contract policy applies."
                ),
            )
        )
    return findings


def run_rules(graph: MetadataGraph, cfg: dict) -> list[Finding]:
    from airgap.detect.findings import normalize_markers
    from airgap.detect.settings import detection_settings

    det, _notes = detection_settings(cfg)  # missing keys fall back to the defaults
    cfg = {**cfg, "detection": det}
    pii_set = normalize_markers(det["pii_markers"])
    findings = rule_r1(graph, cfg, pii_set) + rule_r2(graph, cfg, pii_set)
    findings.sort(key=sort_key)
    return findings
