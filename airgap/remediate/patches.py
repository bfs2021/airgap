"""Generate ready-to-run DataHub remediation code for each finding.

For every finding, Airgap emits a Python snippet using the official DataHub
SDK (`acryl-datahub`) that a data engineer can review and run to fix the issue:
  - R1 -> propagate the PII tag + glossary term onto the leaked fields
  - R2 -> assign an owner to the ownerless asset

These are *proposed* changes (artifacts) — Airgap never writes to DataHub
itself. They live in outputs/patches/ so they can go straight into a PR.
"""
from __future__ import annotations

import os

from airgap.detect.findings import Finding

_HEADER = '''"""Airgap remediation for {fid} — {title}

Severity: {severity}
Review, then run against your DataHub instance.
Requires: pip install acryl-datahub
"""
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    GlobalTagsClass,
    TagAssociationClass,
    GlossaryTermsClass,
    GlossaryTermAssociationClass,
    OwnershipClass,
    OwnerClass,
    OwnershipTypeClass,
    AuditStampClass,
)

GMS = "http://localhost:8080"   # <-- your DataHub GMS
TOKEN = ""                       # <-- your DataHub token
emitter = DatahubRestEmitter(gms_server=GMS, token=TOKEN)

PII_TAG = "urn:li:tag:PII"
SENSITIVE_TERM = "urn:li:glossaryTerm:Classification.Sensitive"
DATASET_URN = "{urn}"
'''

_R1_BODY = '''
# Propagate classification onto the leaked field(s) so PII stays governed.
LEAKED_FIELDS = {fields!r}

for field_path in LEAKED_FIELDS:
    field_urn = f"urn:li:schemaField:({{DATASET_URN}},{{field_path}})"
    emitter.emit(
        MetadataChangeProposalWrapper(
            entityUrn=field_urn,
            aspect=GlobalTagsClass(tags=[TagAssociationClass(tag=PII_TAG)]),
        )
    )
    emitter.emit(
        MetadataChangeProposalWrapper(
            entityUrn=field_urn,
            aspect=GlossaryTermsClass(
                terms=[GlossaryTermAssociationClass(urn=SENSITIVE_TERM)],
                auditStamp=AuditStampClass(time=0, actor="urn:li:corpuser:airgap"),
            ),
        )
    )
    print(f"tagged {{field_urn}}")
'''

_R2_BODY = '''
# Assign an accountable owner to the sensitive asset.
NEW_OWNER = "urn:li:corpGroup:REPLACE_WITH_OWNING_TEAM"

emitter.emit(
    MetadataChangeProposalWrapper(
        entityUrn=DATASET_URN,
        aspect=OwnershipClass(
            owners=[OwnerClass(owner=NEW_OWNER, type=OwnershipTypeClass.DATAOWNER)]
        ),
    )
)
print(f"assigned owner {{NEW_OWNER}} to {{DATASET_URN}}")
'''


def _patch_code(finding: Finding) -> str:
    header = _HEADER.format(
        fid=finding.id,
        title=finding.title,
        severity=finding.severity,
        urn=finding.asset_urn,
    )
    if finding.rule == "R1":
        return header + _R1_BODY.format(fields=finding.leaked_fields)
    if finding.rule == "R2":
        return header + _R2_BODY
    return header


def generate_patches(findings: list[Finding], out_dir: str) -> list[str]:
    patch_dir = os.path.join(out_dir, "patches")
    os.makedirs(patch_dir, exist_ok=True)
    written: list[str] = []
    for f in findings:
        path = os.path.join(patch_dir, f"{f.id}.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_patch_code(f))
        written.append(path)
    return written
