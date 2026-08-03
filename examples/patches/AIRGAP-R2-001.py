"""Airgap remediation for AIRGAP-R2-001 — Ownerless sensitive asset: acme.marketing.marketing_enriched

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
DATASET_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,acme.marketing.marketing_enriched,PROD)"

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
