"""Airgap remediation for AIRGAP-R1-003 — Untagged PII propagation into acme.ml.churn_features

Severity: CRITICAL
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
DATASET_URN = "urn:li:dataset:(urn:li:dataPlatform:feast,acme.ml.churn_features,PROD)"

# Propagate classification onto the leaked field(s) so PII stays governed.
LEAKED_FIELDS = ['phone_raw']

for field_path in LEAKED_FIELDS:
    field_urn = f"urn:li:schemaField:({DATASET_URN},{field_path})"
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
    print(f"tagged {field_urn}")
