## Inspiration

In every data stack we've seen, PII is classified **at the source** — `users.email` gets tagged `PII`, `Email`, `Classification.Sensitive`. The problem is what happens next. That column gets copied, joined, and transformed through staging tables, marts, marketing tables, and ML feature stores — and **the classification doesn't travel with it.** A downstream `marketing_enriched.email` ends up untagged, in a dataset nobody owns, feeding a dashboard the whole company can see.

Auditing this by hand means walking the lineage graph node by node. It doesn't scale. And the "obvious" fix — point an AI agent at your catalog — usually means shipping your schemas and lineage to a **cloud LLM.** For a tool whose entire job is protecting sensitive data, that's self-defeating: you leak the very metadata you're trying to govern.

That contradiction was the spark. We wanted a governance auditor whose defining property is that **the tool protecting your data can't itself leak it.** Hence the name: **Airgap**.

## What it does

Airgap reads its context from **DataHub** — datasets, field-level tags & glossary terms, ownership, and dataset- and column-level lineage — and finds **governance leaks**:

- **R1 — Untagged PII propagation:** a classified field flows through lineage into a downstream field/dataset carrying no equivalent classification.
- **R2 — Ownerless sensitive asset:** a dataset holding PII (directly or by lineage) has no owner, so nobody is accountable.

Each finding is scored by **blast radius** (how many downstream consumers it reaches, escalating to CRITICAL when PII hits a human-facing dashboard), explained in plain language by a **local LLM (Ollama)**, and shipped with a **ready-to-run DataHub SDK patch** to fix it. Every run emits `findings.json`, a Markdown report, an offline visual **lineage leak map**, and remediation code.

The key architectural decision: **detection is deterministic code; the LLM only explains.** That keeps results reproducible and hallucination-free, and confines the model to the low-risk "communication" layer. And because the model is local, **no metadata ever leaves the machine** — you can literally run Airgap with Wi-Fi off.

## How we built it

Airgap is a Python CLI with a source-agnostic core. Every metadata source normalizes into the same `MetadataGraph` (`Asset`, `Field`, `LineageEdge`, `FieldLineage`), so detection runs identically no matter where metadata comes from. There are three sources:

1. **`datahub-lite`** — a real, local, **Docker-free** DataHub. We convert a catalog into genuine DataHub metadata aspects via the official `acryl-datahub` SDK (`SchemaMetadata`, `GlobalTags`, `GlossaryTerms`, `Ownership`, `UpstreamLineage` with `FineGrainedLineage`, `DashboardInfo`/`ChartInfo`), ingest them into a DuckDB-backed **DataHub Lite** instance, and read them back through the `datahub lite` CLI.
2. **`datahub`** — a live GMS instance via the read-only **GraphQL API** (search datasets → schema/tags/ownership → `lineage` + `fineGrainedLineages`).
3. **`fixture`** — a synthetic catalog using DataHub's exact URN and schema model, for a zero-setup demo.

Detection (`R1`/`R2`) traces PII from its **true origins** (sensitive fields with no sensitive upstream) through column-level lineage, flags every downstream point where classification is dropped, and computes blast radius from transitive downstream consumers. The local LLM layer talks only to `localhost:11434`. Remediation generates `MetadataChangeProposalWrapper` code that re-tags fields (R1) or assigns owners (R2).

## Challenges we ran into

- **The public demo went behind SSO.** We planned to read `demo.datahub.com`, but native auth is disabled there now and GraphQL returns 401 — and even with a token, a submission the judges can't reproduce is worthless. This pushed us to a better answer: **DataHub Lite**, a genuinely local DataHub with no Docker and no cloud, which also perfectly reinforces the local-first thesis.
- **Making the fixture indistinguishable from real DataHub.** We didn't want the detection code to "know" it was running on synthetic data. Converting the fixture into real DataHub aspects and round-tripping it through DataHub Lite proved the point: the synthetic run and the real-DataHub run produce the **exact same five findings.**
- **Column-level lineage serialization quirks.** Reading back from DataHub Lite, `ChartInfo.inputs` came through as union objects (`{"string": "urn:..."}`) instead of plain strings, and `schemaField` URNs had to be split back into `(dataset_urn, field_path)` to line columns up with lineage. Small, sharp edges that only surface against real metadata.
- **Keeping the LLM honest.** It was tempting to let the model decide findings. We deliberately didn't — detection stays deterministic, the model only narrates — so results are reproducible and safe to run on real catalogs.

## Accomplishments that we're proud of

- A governance auditor that runs against a **real DataHub with no Docker and no cloud**, and produces identical results on synthetic and real metadata.
- A coherent, defensible thesis — **private by construction** — backed by a demo you can run with the network turned off.
- End-to-end output that a data team would actually use: findings, lineage evidence, a visual leak map, and PR-ready fixes.

## What we learned

Lineage is only as useful as the classification that rides on it — and in practice, that classification silently falls off. We also learned how much cleaner an "agent" is when you split the deterministic decision from the language it's wrapped in: the model becomes a translator, not an oracle. And we learned that **DataHub Lite is a surprisingly great fit for local-first tooling** — a full DataHub metadata model without the operational weight.

## What's next for Airgap

- Two more rules already designed: **R3** (broken classification chain) and **R4** (retention/policy gaps).
- Reading through the **DataHub MCP Server** in addition to GraphQL, so Airgap plugs directly into the agent-context ecosystem.
- A CI mode (`--fail-on-critical`) as a governance gate on every pull request.

**Repo:** https://github.com/zelihaguven/airgap
