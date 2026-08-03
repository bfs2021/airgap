"""Human-readable Markdown report."""
from __future__ import annotations

from datetime import datetime, timezone

from airgap.detect.findings import Finding, Severity

_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "⚪",
}


def _summary_counts(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts


def write_markdown(findings: list[Finding], source_name: str, path: str) -> None:
    counts = _summary_counts(findings)
    lines: list[str] = []
    lines.append("# Airgap Governance Audit")
    lines.append("")
    lines.append(
        f"> Local-first PII lineage audit · source: `{source_name}` · "
        f"generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    lines.append("")
    lines.append(
        "_All analysis ran locally. No metadata was sent to any cloud service._"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|---|---|")
    for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
        if counts.get(sev):
            lines.append(f"| {_EMOJI[sev]} {sev} | {counts[sev]} |")
    lines.append(f"| **Total** | **{len(findings)}** |")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    for f in findings:
        lines.append(f"### {_EMOJI.get(f.severity, '')} {f.id} — {f.title}")
        lines.append("")
        lines.append(f"- **Severity:** {f.severity}")
        lines.append(f"- **Rule:** {f.rule}")
        lines.append(f"- **Asset:** `{f.asset_urn}`")
        if f.leaked_fields:
            lines.append(f"- **Leaked fields:** {', '.join(f.leaked_fields)}")
        lines.append(
            f"- **Blast radius:** {f.blast_radius} downstream consumer(s) "
            f"{f.consumers or ''}"
        )
        lines.append("")
        if f.explanation:
            lines.append(f"> {f.explanation}")
            lines.append("")
        lines.append("**Lineage evidence:**")
        lines.append("")
        for ev in f.evidence:
            lines.append(f"- `{ev}`")
        lines.append("")
        lines.append(f"**Remediation:** {f.remediation}")
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
