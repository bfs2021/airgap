"""Self-contained HTML lineage graph with leak paths highlighted.

No external assets or CDNs — the file is fully offline, consistent with
Airgap's local-first promise. Layout is a simple longest-path layering of the
lineage DAG; contaminated paths leading into findings are drawn in red.
"""
from __future__ import annotations

import html

from airgap.detect.findings import Finding, Severity
from airgap.model import MetadataGraph

_SEV_COLOR = {
    Severity.CRITICAL: "#e5484d",
    Severity.HIGH: "#f76b15",
    Severity.MEDIUM: "#ffb224",
    Severity.LOW: "#8b8d98",
}
_TYPE_COLOR = {"dataset": "#3b82f6", "dashboard": "#8b5cf6", "chart": "#8b5cf6"}

_X_GAP = 250
_Y_GAP = 78
_BOX_W = 190
_BOX_H = 46
_MARGIN = 40


def _depths(graph: MetadataGraph) -> dict[str, int]:
    memo: dict[str, int] = {}

    def depth(urn: str, seen: frozenset[str]) -> int:
        if urn in memo:
            return memo[urn]
        ups = [u for u in graph.upstream(urn) if u not in seen]
        d = 0 if not ups else 1 + max(depth(u, seen | {urn}) for u in ups)
        memo[urn] = d
        return d

    for urn in graph.assets:
        depth(urn, frozenset())
    return memo


def write_graph_html(
    findings: list[Finding], graph: MetadataGraph, source_name: str, path: str
) -> None:
    finding_sev: dict[str, str] = {}
    for f in findings:
        cur = finding_sev.get(f.asset_urn)
        if cur is None or Severity.ORDER[f.severity] < Severity.ORDER[cur]:
            finding_sev[f.asset_urn] = f.severity

    # Contaminated = every finding asset plus its transitive upstreams.
    contaminated: set[str] = set()
    for urn in finding_sev:
        contaminated.add(urn)
        stack = list(graph.upstream(urn))
        while stack:
            u = stack.pop()
            if u in contaminated:
                continue
            contaminated.add(u)
            stack.extend(graph.upstream(u))

    depths = _depths(graph)
    layers: dict[int, list[str]] = {}
    for urn, d in sorted(depths.items(), key=lambda kv: (kv[1], kv[0])):
        layers.setdefault(d, []).append(urn)

    pos: dict[str, tuple[int, int]] = {}
    for d, urns in layers.items():
        for i, urn in enumerate(urns):
            x = _MARGIN + d * _X_GAP
            y = _MARGIN + i * _Y_GAP
            pos[urn] = (x, y)

    width = _MARGIN * 2 + (max(layers) + 1) * _X_GAP
    height = _MARGIN * 2 + max(len(v) for v in layers.values()) * _Y_GAP

    edges_svg: list[str] = []
    for e in graph.edges:
        if e.upstream not in pos or e.downstream not in pos:
            continue
        x1, y1 = pos[e.upstream]
        x2, y2 = pos[e.downstream]
        sx, sy = x1 + _BOX_W, y1 + _BOX_H / 2
        ex, ey = x2, y2 + _BOX_H / 2
        leak = e.upstream in contaminated and e.downstream in contaminated
        color = "#e5484d" if leak else "#c7c9d1"
        w = 2.5 if leak else 1.3
        mx = (sx + ex) / 2
        edges_svg.append(
            f'<path d="M{sx},{sy} C{mx},{sy} {mx},{ey} {ex},{ey}" '
            f'fill="none" stroke="{color}" stroke-width="{w}" '
            f'marker-end="url(#arrow{"R" if leak else ""})"/>'
        )

    nodes_svg: list[str] = []
    for urn, (x, y) in pos.items():
        a = graph.get(urn)
        name = a.name if a else urn
        etype = a.entity_type if a else "dataset"
        if urn in finding_sev:
            stroke = _SEV_COLOR[finding_sev[urn]]
            sw = 3
        elif urn in contaminated:
            stroke = "#e5484d"
            sw = 1.5
        else:
            stroke = _TYPE_COLOR.get(etype, "#8b8d98")
            sw = 1.5
        nodes_svg.append(
            f'<g><rect x="{x}" y="{y}" rx="8" width="{_BOX_W}" height="{_BOX_H}" '
            f'fill="#ffffff" stroke="{stroke}" stroke-width="{sw}"/>'
            f'<text x="{x + 10}" y="{y + 19}" font-size="12" font-weight="600" '
            f'fill="#1a1a1a">{html.escape(name[:26])}</text>'
            f'<text x="{x + 10}" y="{y + 35}" font-size="10" fill="#8b8d98">'
            f'{html.escape(etype)} · {html.escape(a.platform if a else "")}</text>'
            f'<title>{html.escape(urn)}</title></g>'
        )

    svg = f'''<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#c7c9d1"/>
    </marker>
    <marker id="arrowR" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#e5484d"/>
    </marker>
  </defs>
  {"".join(edges_svg)}
  {"".join(nodes_svg)}
</svg>'''

    legend = (
        '<div class="legend">'
        '<span><i style="background:#e5484d"></i>PII leak path / finding</span>'
        '<span><i style="background:#3b82f6"></i>governed dataset</span>'
        '<span><i style="background:#8b5cf6"></i>BI consumer</span>'
        "</div>"
    )

    doc = f'''<!doctype html>
<html><head><meta charset="utf-8"><title>Airgap — Lineage Leak Map</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0;
         background: #f6f7f9; color: #1a1a1a; }}
  header {{ padding: 20px 28px; border-bottom: 1px solid #e6e7eb; background:#fff; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .sub {{ color:#6b6d76; font-size: 13px; }}
  .legend {{ display:flex; gap:20px; padding:12px 28px; font-size:12px; color:#4a4c55; }}
  .legend i {{ display:inline-block; width:11px; height:11px; border-radius:3px;
              margin-right:6px; vertical-align:middle; }}
  .canvas {{ overflow:auto; padding:16px 28px 40px; }}
</style></head>
<body>
  <header>
    <h1>🛡️ Airgap — Lineage Leak Map</h1>
    <div class="sub">source: <code>{html.escape(source_name)}</code> ·
      {len(findings)} finding(s) · analysis ran fully locally</div>
  </header>
  {legend}
  <div class="canvas">{svg}</div>
</body></html>'''

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
