# Airgap — Technical Documentation

> Local-first data governance & PII lineage auditor for DataHub.
> Built for the DataHub Agent Hackathon (Wildcard / Regulatory Automation).

This document explains **what Airgap is, the problem it solves, how it works
end to end, and exactly how DataHub is integrated.**

---

## 1. What Airgap is

Airgap is a command-line agent that audits a data catalog for **PII governance
leaks** — places where sensitive data has flowed downstream through lineage but
lost its classification, or ended up in an asset that nobody owns. It reads its
context from **DataHub** (schemas, tags, glossary terms, ownership, and
lineage), applies deterministic detection rules, and uses a **local LLM
(Ollama)** to turn each finding into a plain-language, compliance-oriented
explanation.

Its defining property: **nothing leaves your machine.** The detection is local
code and the language model is local. The only network calls Airgap makes are
read-only queries to the DataHub instance you explicitly point it at.

> The one-liner: *an air-gapped auditor for the data you can't afford to leak.*

---

## 2. The problem it solves

In a modern data stack, PII is usually classified correctly **at the source**
(e.g. `users.email` is tagged `PII` / `Email` / `Classification.Sensitive`).
The problem is what happens next:

1. That column is copied, joined, and transformed through staging tables, marts,
   marketing tables, and ML feature stores.
2. **Classification does not automatically travel with the data.** A downstream
   `marketing_enriched.email` column often carries no PII tag at all.
3. Those derived assets frequently have **no owner**, so when a regulator or an
   incident asks "who is responsible for this PII?", there's no answer.
4. Auditing this by hand means walking the lineage graph node by node — it does
   not scale.
5. The obvious fix — point an LLM agent at your catalog — usually means shipping
   your schemas and lineage to a **cloud model**. For a tool whose entire job is
   protecting sensitive data, that is self-defeating.

**Airgap closes exactly this gap:** automated, lineage-aware PII leak detection
that runs entirely locally.

---

## 3. What it does (features)

- **Reads DataHub metadata** — datasets, schema fields, field-level tags &
  glossary terms, dataset-level tags, ownership, and dataset- and column-level
  lineage.
- **Detects governance leaks** with two deterministic rules (R1, R2 — see §6).
- **Scores severity by blast radius** — how many downstream consumers a leak
  reaches, escalating to CRITICAL when PII reaches human-facing BI (dashboards,
  charts).
- **Explains findings locally** via Ollama — GDPR-framed, plain-language prose,
  never deciding the finding, only describing it.
- **Produces four artifacts** per run:
  - `findings.json` — machine-readable findings
  - `report.md` — human-readable governance report
  - `lineage_graph.html` — an offline, self-contained lineage leak map
  - `outputs/patches/*.py` — ready-to-run DataHub SDK remediation code
- **Source-agnostic** — the exact same detection runs against a live DataHub
  instance or the bundled synthetic fixture.
- **CI-friendly** — `--fail-on-critical` returns a non-zero exit code when any
  CRITICAL finding is present.

---

## 4. How it works, end to end

```
┌─ source ─────────────┐
│ DataHub (GraphQL)    │  read-only, HTTPS
│   — or —             │
│ bundled fixture JSON │
└──────────┬───────────┘
           │  normalize
           ▼
┌─ MetadataGraph ──────┐   the source-agnostic contract:
│ assets, edges,       │   assets{urn→Asset}, lineage edges,
│ field_edges          │   column-level field edges
└──────────┬───────────┘
           │  run_rules()  (deterministic)
           ▼
┌─ Findings ───────────┐   R1 untagged PII propagation
│ severity, evidence,  │   R2 ownerless sensitive asset
│ blast radius,        │   + blast-radius severity
│ remediation          │
└──────────┬───────────┘
           │  enrich() — local Ollama, localhost:11434 only
           ▼
┌─ Outputs ────────────┐
│ findings.json        │
│ report.md            │
│ lineage_graph.html   │
│ patches/*.py         │
└──────────────────────┘
```

Step by step:

1. **Fetch.** A `MetadataSource` (`FixtureSource` or `DataHubSource`) returns a
   fully normalized `MetadataGraph`. Both sources produce the identical shape,
   so nothing downstream knows or cares where the metadata came from.
2. **Detect.** `run_rules()` applies R1 and R2 over the graph, computing a
   lineage-evidence path and a blast-radius severity for each finding. This is
   plain, unit-tested Python — **no LLM is involved in deciding a finding.**
3. **Explain.** If Ollama is reachable, each finding is sent to a local model
   which returns a 2–3 sentence explanation and urgency assessment. If Ollama is
   not running, Airgap still emits the complete deterministic report.
4. **Emit.** Airgap writes the four artifacts and prints a colored console
   summary.

**Why the split matters:** deterministic detection makes results reproducible
and hallucination-free; the LLM is confined to the "communication" layer where
mistakes are low-risk and easy to review.

---

## 5. How DataHub is integrated

DataHub is Airgap's **context platform** — the source of truth for schema,
classification, ownership, and lineage. Integration happens in
`airgap/sources/datahub.py` (`DataHubSource`) through DataHub's **GraphQL API**,
using only read-only queries.

### 5.1 Discovering datasets
Airgap paginates `search(input: {type: DATASET, query: "*"})` to enumerate every
dataset URN in the catalog.

### 5.2 Reading each dataset
For each URN it queries the `dataset(urn:)` resolver for:
- `platform { name }`
- dataset-level `tags`
- `ownership { owners }`
- `schemaMetadata { fields { fieldPath nativeDataType globalTags glossaryTerms } }`
  — this is where **field-level PII classification** lives
- `fineGrainedLineages` — DataHub's **column-level lineage**, used for precise
  field-to-field leak tracing

### 5.3 Reading lineage
For each dataset it queries the `entity(urn:).lineage(input:{direction: DOWNSTREAM})`
resolver to build the asset-level lineage edges (including dashboards, charts,
and ML entities that consume the data).

### 5.4 Normalization
GraphQL responses are mapped into the `MetadataGraph` model
(`airgap/model.py`): `Asset`, `Field`, `LineageEdge`, `FieldLineage`. DataHub
`schemaField` URNs (`urn:li:schemaField:(<datasetUrn>,<fieldPath>)`) are split
back into `(dataset_urn, field_path)` so column-level lineage lines up with the
schema.

### 5.5 Writing back (remediation)
Airgap never mutates DataHub directly. Instead it **generates** DataHub Python
SDK code (`acryl-datahub`) that a data engineer reviews and runs to fix each
finding — emitting `GlobalTagsClass` / `GlossaryTermsClass` on the leaked fields
(R1) or `OwnershipClass` on the ownerless asset (R2). These artifacts are
designed to drop straight into a pull request.

### 5.6 Three sources, one model
Airgap has three interchangeable metadata sources, all normalizing into the same
`MetadataGraph`:

1. **`datahub-lite` — a real, local, Docker-free DataHub.** This is the primary
   integration for reproducibility. `scripts/setup_datahub_lite.sh` installs
   [DataHub Lite](https://docs.datahub.com/docs/datahub-lite) (a DuckDB-backed
   DataHub), converts the Acme fixture into genuine DataHub metadata aspects via
   the official SDK (`scripts/seed_datahub_lite.py` — `SchemaMetadata`,
   `GlobalTags`, `GlossaryTerms`, `Ownership`, `UpstreamLineage` with
   `FineGrainedLineage`, `DashboardInfo`/`ChartInfo`), and imports them.
   `DataHubLiteSource` then reads them back through the `datahub lite` CLI. This
   proves Airgap runs against real DataHub metadata with **no Docker and no
   cloud** — the whole point of a local-first tool.
2. **`datahub` — live GMS** via GraphQL (§5.1–5.4), for any hosted instance.
3. **`fixture` — synthetic**, zero-setup, using the *same URN format and schema
   model* as real DataHub. Useful for a dependency-free demo and as the seed for
   DataHub Lite.

Because all three produce an identical `MetadataGraph`, the detection engine is
exercised the same way regardless of source — the synthetic fixture and the real
DataHub Lite instance yield the **same five findings**.

---

## 6. Detection rules

### R1 — Untagged PII propagation
A field classified as PII/sensitive flows, through column-level lineage, into a
downstream field/dataset that carries **no equivalent classification.**

Algorithm:
1. Find **true PII origins** — sensitive fields with no sensitive upstream field
   (where PII first enters the graph).
2. BFS the column-level lineage from each origin.
3. Any reached downstream field that is **not** itself classified **and** whose
   dataset carries no PII tag is a leak.
4. Group leaks by offending dataset; attach the full origin→leak lineage path as
   evidence.

Example evidence:
`acme.public.users.email → acme.staging.stg_users.email → acme.analytics.dim_customer.email → acme.marketing.marketing_enriched.email`

### R2 — Ownerless sensitive asset
A dataset that holds sensitive data — directly, or by receiving it through
lineage from a classified source — has **no owner**, so nobody is accountable.

### Severity (blast radius)
Severity is driven by the transitive downstream consumers of the offending
asset:
- **CRITICAL** — reaches a human-facing consumer (dashboard/chart), i.e. PII is
  visible to real users, or blast radius ≥ configured threshold.
- **HIGH** — has downstream consumers, but none human-facing.
- **MEDIUM** — internal only, no downstream consumers yet.

All thresholds and the PII marker vocabulary are configurable in `config.yaml`.

---

## 7. The local LLM layer

`airgap/llm/ollama.py` calls Ollama's `/api/generate` on `localhost:11434`. For
each finding it sends the structured facts (rule, asset, leaked fields, lineage
evidence, blast radius) and asks for a short DPO-facing explanation of the risk
and urgency. Key guarantees:
- The prompt forbids inventing facts beyond what's given.
- A failure or an unreachable Ollama never breaks the audit — the report is
  still produced deterministically.
- No metadata is ever sent anywhere but localhost.

Model is configurable (`qwen2.5:7b` by default; any Ollama model works).

---

## 8. Repository layout

```
airgap/
├── model.py            normalized metadata model (source-agnostic contract)
├── cli.py              CLI: `airgap audit`
├── sources/
│   ├── base.py         MetadataSource interface
│   ├── datahub.py      live DataHub GraphQL source
│   ├── datahub_lite.py local DataHub Lite source (via `datahub lite` CLI)
│   └── fixture.py      synthetic-fixture source
├── detect/
│   ├── findings.py     Finding model, marker matching, severity scoring
│   └── rules.py        R1 + R2 detection
├── llm/ollama.py       local explanation layer
├── report/
│   ├── markdown.py     report.md
│   └── graph_html.py   offline lineage leak map
├── remediate/patches.py  DataHub SDK remediation code generator
└── data/
    ├── config.yaml     bundled default config (copy of the root config.yaml)
    └── acme_datalake.json  synthetic DataHub-shape catalog with planted leaks

examples/                     sample outputs (findings, report, graph, patches)
tests/                        detection and CLI-defaults tests
config.yaml                   markers, thresholds, source & Ollama config
scripts/                      DataHub Lite setup + seeding scripts
docs/                         this document, PRD, writeup, demo film, deck, media
```

---

## 9. Usage

```bash
# Bundled fixture (default, offline)
airgap audit

# Deterministic only (skip the LLM)
airgap audit --no-llm

# Live DataHub
airgap audit --source datahub --url https://your.acryl.io --token $TOKEN

# CI gate
airgap audit --fail-on-critical
```

Config lookup: `--config PATH` if given, else `./config.yaml` in the current
directory, else the default config bundled in `airgap/data/`. Outputs are
written to `./outputs/` in the current directory unless `--out DIR` is given.

---

## 10. Limitations & roadmap

- **Now:** R1 (untagged PII propagation) and R2 (ownerless sensitive asset),
  dataset- and column-level lineage, blast-radius severity, local explanations,
  remediation code generation.
- **Stretch (designed, not yet enabled):** R3 broken-classification-chain, R4
  policy/retention gaps, and reading directly through the **DataHub MCP Server**
  in addition to GraphQL.
- R1 depends on column-level lineage. It walks only `fineGrainedLineages`
  (the graph's `field_edges`) and never falls back to dataset-level lineage,
  so a flow that has no column-level edges produces no R1 finding.
  Dataset-level edges are used only to compute blast radius and severity.
  R2 still flags an ownerless dataset that carries a sensitive marker
  directly, but it can only see PII that arrives through lineage when
  column-level edges exist.
