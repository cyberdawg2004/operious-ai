"""rename probe.* template purposes to the unified resolution.{outcome}.* scheme

Revision ID: 0092_resolution_verdict_template_purpose_rename
Revises: 0091_case_approval_status_rejected
Create Date: 2026-06-23

_apply_resolution_verdict_override (app/runtime/resolution_runtime.py)
generalizes the single-purpose cannot_determine probe dispatch (W4) into
a verdict-agnostic override covering approved/denied/needs_more_info
outcomes uniformly, keyed by "resolution.{outcome}.{outcome_purpose_key}"
instead of the old "probe.missing_{field}" scheme. Renaming the existing
APPROVED template rows in place — rather than having the generic
dispatcher carry a permanent legacy-alias special case for one outcome
— keeps the dispatcher genuinely domain- and history-agnostic.
tenant_knowledge_documents rows of this kind are already edited in
place by TenantConfigurationRuntime.update_knowledge_document (never
superseded by a new row), so a straight UPDATE of template_purpose is
the same mechanism this store already uses for content changes, just
changing the purpose slot instead of the content.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0092_resolution_verdict_template_purpose_rename"
down_revision: Union[str, None] = "0091_case_approval_status_rejected"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tenant_knowledge_documents"
_OLD_PREFIX = "probe."
_NEW_PREFIX = "resolution.needs_more_info."


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE {_TABLE}
            SET template_purpose = :new_prefix
                || substring(template_purpose from :old_prefix_len)
            WHERE document_type = 'template'
              AND template_purpose LIKE :old_like
            """
        ).bindparams(
            new_prefix=_NEW_PREFIX,
            old_prefix_len=len(_OLD_PREFIX) + 1,
            old_like=f"{_OLD_PREFIX}%",
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE {_TABLE}
            SET template_purpose = :old_prefix
                || substring(template_purpose from :new_prefix_len)
            WHERE document_type = 'template'
              AND template_purpose LIKE :new_like
            """
        ).bindparams(
            old_prefix=_OLD_PREFIX,
            new_prefix_len=len(_NEW_PREFIX) + 1,
            new_like=f"{_NEW_PREFIX}%",
        )
    )
