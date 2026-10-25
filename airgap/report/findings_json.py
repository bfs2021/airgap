"""Versioned machine-readable findings (``findings.json``)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from airgap import __version__
from airgap.detect.findings import Finding

#: Version of the ``findings.json`` layout. Bump it when a key is removed,
#: renamed or changes meaning. Adding a key does not bump it.
SCHEMA_VERSION = 1


def utc_now() -> str:
    """Current UTC time as ISO 8601 with a ``Z`` suffix, to the second."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def findings_document(
    findings: list[Finding], source_name: str, generated_at: str
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "airgap_version": __version__,
        "generated_at": generated_at,
        "source": source_name,
        "findings": [f.to_dict() for f in findings],
    }


def write_findings_json(
    findings: list[Finding], source_name: str, path: str, generated_at: str
) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(findings_document(findings, source_name, generated_at), fh, indent=2)
