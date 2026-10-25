"""SARIF 2.1.0 output, for code-scanning and other SARIF tools.

Each finding becomes one ``result``. R1 and R2 are the ``rules``. The asset
URN is a logical location, because a finding points at a catalog asset, not
at a file.
"""
from __future__ import annotations

import hashlib
import json

from airgap import __version__
from airgap.detect.findings import Finding, Severity

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/"
    "sarif-schema-2.1.0.json"
)
_REPO = "https://github.com/zelihaguven/airgap"

#: Airgap severity to SARIF ``level``. SARIF has no level above ``error``,
#: so CRITICAL and HIGH both map to it. The Airgap severity itself is kept
#: in ``properties.severity``.
LEVELS = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
}

RULES = [
    {
        "id": "R1",
        "name": "UntaggedPiiPropagation",
        "shortDescription": {"text": "Untagged PII propagation"},
        "fullDescription": {
            "text": (
                "A sensitive field reaches, through column-level lineage, a "
                "downstream field that has no sensitive marker on a dataset "
                "that has no sensitive tag."
            )
        },
        "helpUri": f"{_REPO}#how-detection-works",
        "defaultConfiguration": {"level": "error"},
    },
    {
        "id": "R2",
        "name": "OwnerlessSensitiveAsset",
        "shortDescription": {"text": "Ownerless sensitive asset"},
        "fullDescription": {
            "text": (
                "A dataset with no owner that either carries a sensitive "
                "marker itself or receives sensitive fields through "
                "column-level lineage."
            )
        },
        "helpUri": f"{_REPO}#how-detection-works",
        "defaultConfiguration": {"level": "error"},
    },
]
_RULE_INDEX = {r["id"]: i for i, r in enumerate(RULES)}


def _fingerprint(f: Finding) -> str:
    # Finding IDs are numbered per run, so they cannot identify a finding
    # across runs. Rule, asset and leaked fields can.
    key = "\n".join([f.rule, f.asset_urn, *sorted(f.leaked_fields)])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _result(f: Finding) -> dict:
    text = f.title
    if f.leaked_fields:
        text += f". Leaked fields: {', '.join(f.leaked_fields)}."
    result: dict = {
        "ruleId": f.rule,
        "level": LEVELS.get(f.severity, "warning"),
        "message": {"text": text},
        "locations": [
            {
                "logicalLocations": [
                    {"name": f.asset_name, "fullyQualifiedName": f.asset_urn}
                ]
            }
        ],
        "partialFingerprints": {"airgapFinding/v1": _fingerprint(f)},
        "properties": {
            "id": f.id,
            "severity": f.severity,
            "blast_radius": f.blast_radius,
            "consumers": f.consumers,
            "leaked_fields": f.leaked_fields,
            "evidence": f.evidence,
            "remediation": f.remediation,
        },
    }
    if f.rule in _RULE_INDEX:
        result["ruleIndex"] = _RULE_INDEX[f.rule]
    if f.explanation:
        result["properties"]["explanation"] = f.explanation
    return result


def sarif_document(
    findings: list[Finding], source_name: str, generated_at: str
) -> dict:
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "airgap",
                        "version": __version__,
                        "semanticVersion": __version__,
                        "informationUri": _REPO,
                        "rules": RULES,
                    }
                },
                "invocations": [
                    {"executionSuccessful": True, "endTimeUtc": generated_at}
                ],
                "results": [_result(f) for f in findings],
                "properties": {"source": source_name},
            }
        ],
    }


def write_sarif(
    findings: list[Finding], source_name: str, path: str, generated_at: str
) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(sarif_document(findings, source_name, generated_at), fh, indent=2)
