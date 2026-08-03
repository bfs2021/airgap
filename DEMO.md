# Demo script (<3 min)

Recording checklist for the hackathon video. Keep it under 3 minutes.

## 0:00–0:20 — The problem
> "PII gets tagged at the source, but as data flows through the warehouse into
> dashboards and ML features, the classification doesn't travel with it. And if
> you automate the audit with a cloud LLM, you leak the very metadata you're
> trying to protect."

Show `README.md` problem section on screen.

## 0:20–0:45 — Run it
Terminal:
```bash
airgap audit
```
Point out the live console: assets loaded, 5 findings, `Explaining findings
locally via Ollama` — emphasize **local**.

## 0:45–1:30 — The report
Open `outputs/report.md`. Walk the top CRITICAL finding:
- leaked fields `email, name`
- the **lineage evidence path** `users.email → stg_users → dim_customer → marketing_enriched.email`
- the local-LLM explanation (GDPR framing)
- severity spectrum: CRITICAL / HIGH / MEDIUM

## 1:30–2:05 — The leak map
Open `outputs/lineage_graph.html`. Trace the red path from `users` fanning out
into the four flagged assets, colored by severity. Contrast with the gray,
properly-governed `Executive Revenue Dashboard`.

## 2:05–2:35 — Remediation + it's a real DataHub integration
- Open `outputs/patches/AIRGAP-R1-001.py` — ready-to-run DataHub SDK code that
  re-tags the leaked fields. "This goes straight into a PR."
- Show `airgap audit --source datahub --url ... --token ...` in the README —
  same detection runs against any live DataHub instance.

## 2:35–3:00 — The kicker: prove it's local
Split screen: run the audit while showing a network monitor (e.g. `nettop` or
Little Snitch). Traffic goes only to `localhost:11434` (Ollama). No cloud.
> "An air-gapped auditor for the data you can't afford to leak."

## Assets to have open
- Terminal in the repo root (venv activated)
- `outputs/report.md`
- `outputs/lineage_graph.html` in a browser
- `outputs/patches/AIRGAP-R1-001.py`
