"""MVP-1 extraction schema agnosticism closure.

Revision ID: 0094_mvp1_extraction_schema_agnosticism
Revises: 0093_action_approval_proposed_by
Create Date: 2026-07-03

No DDL changes.

extraction_schema lives entirely in the parameters JSONB column of
tenant_governance_policies, which has existed since Phase 2.5-A
(0016_governance_policies or earlier).  There is no new column, table,
or index — the schema is a structured sub-object within parameters, parsed
and validated by parse_extraction_schema() at policy-load time.

eligibility_field_mappings likewise lives in the parameters JSONB of
warranty_refund_rules governance policy records.

What this migration documents:
1. ExtractionFieldSpec / ExtractionSchema types added to cognition/extraction.py
2. Resolution taxonomy policy parser extended to parse extraction_schema
3. All five Site 4 cascade sites thread the tenant's configured field names
   (LLM prompt, auto-approval gate, eligibility binding, payload builders,
   eligibility field-walker)
4. WarrantyRefundPolicy.eligibility_field_mappings added to decouple
   eligibility roles from hardcoded e-commerce field names
5. Cross-policy integrity guards added to
   tenant_config_change_request_service.py:
   - _validate_warranty_refund_role_field_references (money-path guard)
   - _validate_taxonomy_schema_role_consistency (money-path guard)
6. Generic payload/target builders for non-commerce action operations
7. inventory_availability.py uses get_field() for domain-agnostic field access

Alembic head advances to record MVP-1 closure in the migration chain even
though no schema changes are required.
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "0094_mvp1_extraction_schema_agnosticism"
down_revision: Union[str, None] = "0093_action_approval_proposed_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
