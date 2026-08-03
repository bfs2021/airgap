# Airgap Governance Audit

> Local-first PII lineage audit · source: `datahub-lite` · generated 2026-08-03 19:14 UTC

_All analysis ran locally. No metadata was sent to any cloud service._

## Summary

| Severity | Count |
|---|---|
| 🔴 CRITICAL | 3 |
| 🟠 HIGH | 1 |
| 🟡 MEDIUM | 1 |
| **Total** | **5** |

## Findings

### 🔴 AIRGAP-R1-002 — Untagged PII propagation into acme.marketing.marketing_enriched

- **Severity:** CRITICAL
- **Rule:** R1
- **Asset:** `urn:li:dataset:(urn:li:dataPlatform:snowflake,acme.marketing.marketing_enriched,PROD)`
- **Leaked fields:** email, name
- **Blast radius:** 1 downstream consumer(s) {'dashboard': 1}

> The finding indicates that personally identifiable information (PII) such as email and name are being propagated into the `acme.marketing.marketing_enriched` dataset without proper tagging, which violates data governance rules. This is a critical compliance/privacy risk under GDPR, as it exposes sensitive user data unnecessarily. The urgency is high due to the severity marked as CRITICAL and the potential for this data to be accessed by one downstream consumer (the dashboard).

**Lineage evidence:**

- `acme.public.users.email -> acme.staging.stg_users.email -> acme.analytics.dim_customer.email -> acme.marketing.marketing_enriched.email`
- `acme.public.users.full_name -> acme.staging.stg_users.full_name -> acme.analytics.dim_customer.name -> acme.marketing.marketing_enriched.name`

**Remediation:** Apply the PII/Sensitive classification (and matching glossary term) to field(s) email, name on acme.marketing.marketing_enriched, or mask/drop them before this asset. Propagate the term from the upstream classified column.

---

### 🔴 AIRGAP-R1-003 — Untagged PII propagation into acme.ml.churn_features

- **Severity:** CRITICAL
- **Rule:** R1
- **Asset:** `urn:li:dataset:(urn:li:dataPlatform:feast,acme.ml.churn_features,PROD)`
- **Leaked fields:** phone_raw
- **Blast radius:** 1 downstream consumer(s) {'chart': 1}

> The finding indicates that sensitive PII (Personal Identifiable Information) in the form of `phone_raw` is being propagated into the `acme.ml.churn_features` dataset without proper tagging. This violates GDPR requirements for data minimization and transparency, as it exposes personal phone numbers in a machine learning feature set. The critical severity and immediate downstream consumption by one chart make this an urgent risk that needs to be addressed quickly to prevent potential privacy breaches and compliance issues.

**Lineage evidence:**

- `acme.public.users.phone -> acme.staging.stg_users.phone -> acme.analytics.dim_customer.phone -> acme.ml.churn_features.phone_raw`

**Remediation:** Apply the PII/Sensitive classification (and matching glossary term) to field(s) phone_raw on acme.ml.churn_features, or mask/drop them before this asset. Propagate the term from the upstream classified column.

---

### 🔴 AIRGAP-R2-001 — Ownerless sensitive asset: acme.marketing.marketing_enriched

- **Severity:** CRITICAL
- **Rule:** R2
- **Asset:** `urn:li:dataset:(urn:li:dataPlatform:snowflake,acme.marketing.marketing_enriched,PROD)`
- **Blast radius:** 1 downstream consumer(s) {'dashboard': 1}

> The asset `acme.marketing.marketing_enriched` contains sensitive data, including PII, with no assigned owner. This lack of ownership and oversight poses a critical compliance risk under GDPR, as it could lead to unauthorized access or misuse of personal data. The urgency is high due to the severity marked as CRITICAL and the potential exposure through one downstream consumer (the dashboard).

**Lineage evidence:**

- `acme.marketing.marketing_enriched receives PII via lineage from an upstream classified source but has no assigned owner.`

**Remediation:** Assign an accountable owner (team or user) to acme.marketing.marketing_enriched in DataHub, and confirm a retention/data-contract policy applies.

---

### 🟠 AIRGAP-R1-004 — Untagged PII propagation into acme.analytics.user_backfill

- **Severity:** HIGH
- **Rule:** R1
- **Asset:** `urn:li:dataset:(urn:li:dataPlatform:snowflake,acme.analytics.user_backfill,PROD)`
- **Leaked fields:** phone
- **Blast radius:** 1 downstream consumer(s) {'dataset': 1}

> The finding indicates that sensitive PII (phone numbers) are being propagated into the `acme.analytics.user_backfill` dataset without proper tagging, which violates data governance rules. This is a high-severity risk under GDPR as it could lead to unauthorized processing of personal data. Immediate action is required to address this issue and ensure compliance.

**Lineage evidence:**

- `acme.public.users.phone -> acme.staging.stg_users.phone -> acme.analytics.dim_customer.phone -> acme.analytics.user_backfill.phone`

**Remediation:** Apply the PII/Sensitive classification (and matching glossary term) to field(s) phone on acme.analytics.user_backfill, or mask/drop them before this asset. Propagate the term from the upstream classified column.

---

### 🟡 AIRGAP-R1-001 — Untagged PII propagation into acme.analytics.tmp_user_export

- **Severity:** MEDIUM
- **Rule:** R1
- **Asset:** `urn:li:dataset:(urn:li:dataPlatform:snowflake,acme.analytics.tmp_user_export,PROD)`
- **Leaked fields:** email
- **Blast radius:** 0 downstream consumer(s) 

> The finding indicates that personally identifiable information (PII) in the form of email addresses is being propagated into `acme.analytics.tmp_user_export` without proper tagging, which could lead to compliance issues under GDPR. This is a medium-severity risk because it involves handling PII, and urgent attention is needed to ensure this data is properly managed and protected.

**Lineage evidence:**

- `acme.public.users.email -> acme.staging.stg_users.email -> acme.analytics.dim_customer.email -> acme.analytics.tmp_user_export.email`

**Remediation:** Apply the PII/Sensitive classification (and matching glossary term) to field(s) email on acme.analytics.tmp_user_export, or mask/drop them before this asset. Propagate the term from the upstream classified column.

---
