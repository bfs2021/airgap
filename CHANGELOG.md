# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - Unreleased

First public release, published on PyPI as `airgap-datahub`. The command and
the import name are `airgap`.

### Added

- `airgap audit` CLI with `--config`, `--source`, `--url`, `--token`,
  `--model`, `--no-llm`, `--out` and `--fail-on-critical` (exit code 2 when
  any CRITICAL finding exists, for CI use).
- Three metadata sources that normalize into one `MetadataGraph` model:
  - `fixture`: the bundled synthetic Acme catalog
    (`fixtures/acme_datalake.json`), fully offline.
  - `datahub-lite`: a local, Docker-free DataHub Lite instance, read through
    the `datahub lite` CLI (`schemaMetadata`, `ownership`, `upstreamLineage`
    with `fineGrainedLineages`, `dashboardInfo`/`chartInfo`).
  - `datahub`: a live DataHub GMS over read-only GraphQL, with optional
    bearer token.
- Deterministic detection rules:
  - **R1, untagged PII propagation**: a field classified as sensitive flows
    through column-level lineage into a downstream field or dataset with no
    equivalent classification.
  - **R2, ownerless sensitive asset**: a dataset that holds sensitive data,
    directly or through lineage, has no owner.
- Severity scoring by blast radius (transitive downstream consumers).
  Human-facing consumers (dashboards, charts) escalate a finding to CRITICAL.
  Thresholds and the PII marker vocabulary are configurable in `config.yaml`.
- Lineage evidence paths on every finding.
- Optional explanations from a local Ollama model (localhost only). The LLM
  never decides findings, and the audit still completes if Ollama is
  unreachable.
- Outputs: `findings.json`, `report.md`, a self-contained offline
  `lineage_graph.html` leak map, and one reviewable DataHub SDK remediation
  script per finding in `patches/`. Airgap never writes to DataHub itself.
- `scripts/setup_datahub_lite.sh` and `scripts/seed_datahub_lite.py` to stand
  up and seed a local DataHub Lite with the Acme catalog.
- Detection regression tests against the Acme fixture (`tests/`).
- Sample outputs in `examples/`, plus documentation, PRD, demo film, slide
  deck and media in `docs/`.
- GitHub Actions: tests on Python 3.10–3.12, and PyPI Trusted Publishing on
  release.

[Unreleased]: https://github.com/zelihaguven/airgap/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zelihaguven/airgap/releases/tag/v0.1.0
