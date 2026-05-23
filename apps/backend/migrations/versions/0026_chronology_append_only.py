"""chronology append-only hardening (Phase B)

Revision ID: 0026_chronology_append_only
Revises: 0025_multi_tenant_hardening
Create Date: 2026-05-23 00:00:00.000000
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Union, cast

import sqlalchemy as sa
from alembic import op

revision: str = "0026_chronology_append_only"
down_revision: Union[str, None] = "0025_multi_tenant_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHRONOLOGY_NAMESPACE = uuid.UUID("c7b7bfc2-5b44-5a25-9b10-4ab18c18e537")
BOOTSTRAP_APPROVAL_ID = str(
    uuid.uuid5(CHRONOLOGY_NAMESPACE, "operious:bootstrap:initial")
)


def upgrade() -> None:
    _add_chronology_columns()
    _backfill_knowledge_version_hashes()
    _backfill_policy_hashes()
    _backfill_execution_governance_hashes()
    _enforce_non_null_lineage()
    _replace_version_uniques()


def downgrade() -> None:
    op.drop_constraint(
        "uq_tenant_execution_governance_configurations_tenant_version",
        "tenant_execution_governance_configurations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_tenant_execution_governance_configurations_tenant",
        "tenant_execution_governance_configurations",
        ["tenant_id"],
    )
    op.drop_constraint(
        "uq_tenant_governance_policies_tenant_type_version",
        "tenant_governance_policies",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_tenant_governance_policies_tenant_type",
        "tenant_governance_policies",
        ["tenant_id", "policy_type"],
    )
    op.alter_column(
        "tenant_knowledge_document_versions",
        "source_approval_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    for table in (
        "tenant_execution_governance_configurations",
        "tenant_governance_policies",
    ):
        op.drop_index(_source_approval_index_name(table), table_name=table)
        op.drop_column(table, "previous_version_sha256")
        op.drop_column(table, "content_sha256")
        op.drop_column(table, "source_approval_id")
    op.drop_column("tenant_knowledge_document_versions", "previous_version_sha256")
    op.drop_column("tenant_knowledge_document_versions", "content_sha256")


def _add_chronology_columns() -> None:
    op.add_column(
        "tenant_knowledge_document_versions",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "tenant_knowledge_document_versions",
        sa.Column("previous_version_sha256", sa.String(length=64), nullable=True),
    )
    for table in (
        "tenant_governance_policies",
        "tenant_execution_governance_configurations",
    ):
        op.add_column(
            table,
            sa.Column("source_approval_id", sa.String(length=255), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("content_sha256", sa.String(length=64), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("previous_version_sha256", sa.String(length=64), nullable=True),
        )
        op.create_index(
            _source_approval_index_name(table),
            table,
            ["source_approval_id"],
        )


def _backfill_knowledge_version_hashes() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT version_id, tenant_id, document_id, version, title, content,
                   document_type, status, uploaded_by, source_approval_id, metadata
            FROM tenant_knowledge_document_versions
            ORDER BY tenant_id, document_id, version
            """
        )
    ).mappings()
    previous_by_document: dict[tuple[str, str], str] = {}
    for row in rows:
        source_approval_id = row["source_approval_id"] or BOOTSTRAP_APPROVAL_ID
        metadata = _mapping(row["metadata"])
        content_sha256 = _canonical_sha256(
            {
                "tenant_id": row["tenant_id"],
                "document_id": str(row["document_id"]),
                "version": row["version"],
                "title": row["title"],
                "content": row["content"],
                "document_type": row["document_type"],
                "status": row["status"],
                "uploaded_by": row["uploaded_by"],
                "source_approval_id": source_approval_id,
                "metadata": metadata,
            }
        )
        key = (row["tenant_id"], str(row["document_id"]))
        previous_sha256 = previous_by_document.get(key)
        bind.execute(
            sa.text(
                """
                UPDATE tenant_knowledge_document_versions
                SET source_approval_id = :source_approval_id,
                    content_sha256 = :content_sha256,
                    previous_version_sha256 = :previous_version_sha256
                WHERE version_id = :version_id
                """
            ),
            {
                "version_id": row["version_id"],
                "source_approval_id": source_approval_id,
                "content_sha256": content_sha256,
                "previous_version_sha256": previous_sha256,
            },
        )
        previous_by_document[key] = content_sha256


def _backfill_policy_hashes() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT policy_id, tenant_id, policy_type, parameters, status, version,
                   approved_by, effective_from
            FROM tenant_governance_policies
            ORDER BY tenant_id, policy_type, version
            """
        )
    ).mappings()
    previous_by_policy: dict[tuple[str, str], str] = {}
    for row in rows:
        content_sha256 = _canonical_sha256(
            {
                "tenant_id": row["tenant_id"],
                "policy_type": row["policy_type"],
                "parameters": _mapping(row["parameters"]),
                "status": row["status"],
                "version": row["version"],
                "approved_by": row["approved_by"],
                "effective_from": _iso(row["effective_from"]),
                "source_approval_id": BOOTSTRAP_APPROVAL_ID,
            }
        )
        key = (row["tenant_id"], row["policy_type"])
        bind.execute(
            sa.text(
                """
                UPDATE tenant_governance_policies
                SET source_approval_id = :source_approval_id,
                    content_sha256 = :content_sha256,
                    previous_version_sha256 = :previous_version_sha256
                WHERE policy_id = :policy_id
                """
            ),
            {
                "policy_id": row["policy_id"],
                "source_approval_id": BOOTSTRAP_APPROVAL_ID,
                "content_sha256": content_sha256,
                "previous_version_sha256": previous_by_policy.get(key),
            },
        )
        previous_by_policy[key] = content_sha256


def _backfill_execution_governance_hashes() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT config_id, tenant_id, status, execution_quota, throughput_limit,
                   throughput_window_minutes, governance_budget_limit,
                   governance_budget_window_minutes, circuit_failure_threshold,
                   circuit_window_minutes, circuit_cooldown_minutes, version,
                   configured_by, metadata
            FROM tenant_execution_governance_configurations
            ORDER BY tenant_id, version
            """
        )
    ).mappings()
    previous_by_tenant: dict[str, str] = {}
    for row in rows:
        content_sha256 = _canonical_sha256(
            {
                "tenant_id": row["tenant_id"],
                "status": row["status"],
                "execution_quota": row["execution_quota"],
                "throughput_limit": row["throughput_limit"],
                "throughput_window_minutes": row["throughput_window_minutes"],
                "governance_budget_limit": row["governance_budget_limit"],
                "governance_budget_window_minutes": row[
                    "governance_budget_window_minutes"
                ],
                "circuit_failure_threshold": row["circuit_failure_threshold"],
                "circuit_window_minutes": row["circuit_window_minutes"],
                "circuit_cooldown_minutes": row["circuit_cooldown_minutes"],
                "version": row["version"],
                "configured_by": row["configured_by"],
                "source_approval_id": BOOTSTRAP_APPROVAL_ID,
                "metadata": _mapping(row["metadata"]),
            }
        )
        tenant_id = row["tenant_id"]
        bind.execute(
            sa.text(
                """
                UPDATE tenant_execution_governance_configurations
                SET source_approval_id = :source_approval_id,
                    content_sha256 = :content_sha256,
                    previous_version_sha256 = :previous_version_sha256
                WHERE config_id = :config_id
                """
            ),
            {
                "config_id": row["config_id"],
                "source_approval_id": BOOTSTRAP_APPROVAL_ID,
                "content_sha256": content_sha256,
                "previous_version_sha256": previous_by_tenant.get(tenant_id),
            },
        )
        previous_by_tenant[tenant_id] = content_sha256


def _enforce_non_null_lineage() -> None:
    for table in (
        "tenant_knowledge_document_versions",
        "tenant_governance_policies",
        "tenant_execution_governance_configurations",
    ):
        op.alter_column(
            table,
            "source_approval_id",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        op.alter_column(
            table,
            "content_sha256",
            existing_type=sa.String(length=64),
            nullable=False,
        )


def _replace_version_uniques() -> None:
    op.drop_constraint(
        "uq_tenant_governance_policies_tenant_type",
        "tenant_governance_policies",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_tenant_governance_policies_tenant_type_version",
        "tenant_governance_policies",
        ["tenant_id", "policy_type", "version"],
    )
    op.drop_constraint(
        "uq_tenant_execution_governance_configurations_tenant",
        "tenant_execution_governance_configurations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_tenant_execution_governance_configurations_tenant_version",
        "tenant_execution_governance_configurations",
        ["tenant_id", "version"],
    )


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(k): _json_safe(v) for k, v in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [_json_safe(item) for item in sequence]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, Any], value)
        return {str(key): item for key, item in mapping.items()}
    return {}


def _iso(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return str(value.isoformat())
    return str(value)


def _source_approval_index_name(table: str) -> str:
    if table == "tenant_execution_governance_configurations":
        return "ix_tenant_exec_gov_configs_source_approval"
    if table == "tenant_governance_policies":
        return "ix_tenant_gov_policies_source_approval"
    raise ValueError(f"unexpected chronology table {table!r}")
