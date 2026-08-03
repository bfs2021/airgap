# 🛡️ Airgap

**Local-first data governance & PII lineage auditor for [DataHub](https://datahubproject.io).**
Finds where sensitive data leaks downstream — without a single byte of your metadata ever leaving your machine.

> Built for the **DataHub Agent Hackathon** (Wildcard / Regulatory Automation).

---

## The problem

PII gets classified correctly at the source (`users.email` → `PII`). But as that
data flows through dozens of transforms, dashboards, and ML features, **the
classification doesn't travel with it.** The result:

- PII lands in untagged downstream tables and dashboards → GDPR/KVKK exposure.
- Those derived assets often have **no owner** → nobody is accountable.
- Auditing it means walking the lineage graph by hand → doesn't scale.
- Automating it usually means shipping your schema/metadata to a **cloud LLM** —
  so the tool meant to protect sensitive data becomes a new way to leak it.

## The idea

Airgap reads DataHub's metadata (tags, glossary terms, column-level
classification, lineage, ownership), walks the lineage graph, and flags
**governance leaks** with deterministic rules. It then uses a **local Ollama
model** to explain each finding in plain language.

**Detection is plain, testable code. The LLM only explains — it never decides.**
That makes results reproducible and hallucination-free, and it means the whole
audit runs offline.

> The one-liner: **an air-gapped auditor for the data you can't afford to leak.**

---

## Quickstart

```bash
git clone <your-fork-url> airgap && cd airgap
python3 -m venv .venv && ./.venv/bin/pip install -e .

# Audit the bundled synthetic catalog (zero setup, fully offline)
./.venv/bin/airgap audit
```

Outputs land in `outputs/`:
- `findings.json` — machine-readable findings
- `report.md` — human-readable governance report

Skip the LLM (deterministic only) with `--no-llm`. See `examples/` for sample output.

### Requirements
- Python 3.10+
- (optional) [Ollama](https://ollama.com) running locally for prose explanations
  — `ollama pull qwen2.5:7b`. Without it, Airgap still produces the full
  deterministic report.

---

## Run against a REAL DataHub — no Docker, no cloud

Airgap ships with a one-command setup that stands up a **local, Docker-free
DataHub** ([DataHub Lite](https://docs.datahub.com/docs/datahub-lite) — a DuckDB-backed
instance), seeds it with the Acme catalog as genuine DataHub metadata aspects,
and imports it:

```bash
bash scripts/setup_datahub_lite.sh
./.venv/bin/airgap audit --source datahub-lite
```

Airgap then reads real DataHub metadata back — `schemaMetadata` with field-level
tags & glossary terms, `ownership`, `upstreamLineage` with column-level
`fineGrainedLineages`, and `dashboardInfo` — through the `datahub lite` CLI, and
runs the **exact same detection** it runs on the fixture. This is Airgap's thesis
in one line: **a local-first governance auditor reading from a local-first DataHub.**

## Auditing a live DataHub (GMS)

The same detection also runs against any hosted DataHub via GraphQL:

```bash
./.venv/bin/airgap audit --source datahub \
  --url https://your-company.acryl.io \
  --token $DATAHUB_TOKEN
```

Only read-only queries are issued. LLM calls always go only to localhost.

### The three sources, one model
`fixture` (zero setup) · `datahub-lite` (real DataHub, local, no Docker) ·
`datahub` (live GMS). All normalize into the same `MetadataGraph`, so detection
is identical regardless of source.

---

## How detection works

| Rule | Detects |
|---|---|
| **R1 — Untagged PII propagation** | A field classified as PII/sensitive flows, through column-level lineage, into a downstream field/dataset carrying no equivalent classification. |
| **R2 — Ownerless sensitive asset** | A dataset that holds sensitive data (directly or by lineage) has no owner — nobody is accountable. |

**Severity** is driven by *blast radius*: the transitive downstream consumers of
the leaking asset. Human-facing consumers (dashboards, charts) escalate a leak to
CRITICAL, because that's PII reaching real eyes.

Every finding ships with the **lineage evidence path** (`users.email → stg_users.email
→ dim_customer.email → marketing_enriched.email`) so it's auditable, not a black box.

---

## Architecture

```
DataHub (GraphQL, read-only)  ─┐
                               ├─► normalize ─► detect (R1/R2 + blast radius)
bundled fixture (JSON)        ─┘                     │
                                                     ▼
                              local Ollama ◄──── explain findings
                              (localhost only)       │
                                                     ▼
                                    outputs/ findings.json + report.md
```

- `airgap/model.py` — normalized metadata model (the source-agnostic contract)
- `airgap/sources/` — `datahub` (live GraphQL) + `fixture` (synthetic)
- `airgap/detect/` — deterministic rules + severity
- `airgap/llm/` — local Ollama explanation layer
- `airgap/report/` — Markdown / JSON output

---

## License

Apache-2.0. See [LICENSE](LICENSE).
