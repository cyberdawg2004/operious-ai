"""create tenant knowledge chunk and vector tables (Phase 5-A)

Revision ID: 0020_tenant_knowledge_vectors
Revises: 0019_tenant_topology_config
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_tenant_knowledge_vectors"
down_revision: Union[str, None] = "0019_tenant_topology_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_knowledge_chunks",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_tenant_knowledge_chunks_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "document_version >= 1",
            name=op.f("ck_tenant_knowledge_chunks_document_version_positive"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_tenant_knowledge_chunks_ordinal_nonnegative"),
        ),
        sa.CheckConstraint(
            "token_count >= 0",
            name=op.f("ck_tenant_knowledge_chunks_token_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "char_start >= 0",
            name=op.f("ck_tenant_knowledge_chunks_char_start_nonnegative"),
        ),
        sa.CheckConstraint(
            "char_end >= char_start",
            name=op.f("ck_tenant_knowledge_chunks_char_span_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_tenant_knowledge_chunks_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["tenant_knowledge_documents.document_id"],
            name="fk_tenant_knowledge_chunks_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "chunk_id",
            name=op.f("pk_tenant_knowledge_chunks"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "document_version",
            "ordinal",
            name="uq_tenant_knowledge_chunks_document_version_ordinal",
        ),
    )
    for col in ("tenant_id", "document_id", "content_hash"):
        op.create_index(
            op.f(f"ix_tenant_knowledge_chunks_{col}"),
            "tenant_knowledge_chunks",
            [col],
        )
    op.create_index(
        "ix_tenant_knowledge_chunks_tenant_document_current",
        "tenant_knowledge_chunks",
        ["tenant_id", "document_id", "is_current"],
    )

    op.create_table(
        "tenant_knowledge_vectors",
        sa.Column("vector_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector_index_name", sa.String(length=255), nullable=False),
        sa.Column("vector", postgresql.JSONB(), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_tenant_knowledge_vectors_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "document_version >= 1",
            name=op.f("ck_tenant_knowledge_vectors_document_version_positive"),
        ),
        sa.CheckConstraint(
            "dimensions > 0",
            name=op.f("ck_tenant_knowledge_vectors_dimensions_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_tenant_knowledge_vectors_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["tenant_knowledge_chunks.chunk_id"],
            name="fk_tenant_knowledge_vectors_chunk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["tenant_knowledge_documents.document_id"],
            name="fk_tenant_knowledge_vectors_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "vector_id",
            name=op.f("pk_tenant_knowledge_vectors"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "chunk_id",
            "provider",
            "model",
            "vector_index_name",
            name="uq_tenant_knowledge_vectors_chunk_provider_model_index",
        ),
    )
    for col in (
        "tenant_id",
        "chunk_id",
        "document_id",
        "vector_index_name",
    ):
        op.create_index(
            op.f(f"ix_tenant_knowledge_vectors_{col}"),
            "tenant_knowledge_vectors",
            [col],
        )
    op.create_index(
        "ix_tenant_knowledge_vectors_tenant_index_current",
        "tenant_knowledge_vectors",
        ["tenant_id", "vector_index_name", "is_current"],
    )


def downgrade() -> None:
    op.drop_table("tenant_knowledge_vectors")
    op.drop_table("tenant_knowledge_chunks")
