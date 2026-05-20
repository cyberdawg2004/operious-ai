"""create memory documents/chunks/embeddings tables.

Sprint G — operational memory infrastructure foundations.

Three tables, all CASCADE-linked:

    documents (1) ──< (N) document_chunks (1) ──< (1..N) chunk_embeddings

`chunk_embeddings` is many-to-one to `document_chunks` because one
chunk can be embedded multiple times with different models/providers/
vector indexes — that's what makes A/B retrieval comparisons and
embedding-model migrations possible without re-ingesting source
documents.

The (chunk_id, provider, model, vector_index_name) UNIQUE constraint
is what makes ingestion idempotent: replays insert no duplicates.

Revision ID: 0003_memory
Revises: 0002_orchestration
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_memory"
down_revision: Union[str, None] = "0002_orchestration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_index_if_exists(name: str) -> None:
    op.execute(sa.text(f'DROP INDEX IF EXISTS "{name}"'))


def _drop_table_if_exists(name: str) -> None:
    op.execute(sa.text(f'DROP TABLE IF EXISTS "{name}"'))


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(
        op.f("ix_documents_content_hash"),
        "documents",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documents_request_id"),
        "documents",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documents_source"),
        "documents",
        ["source"],
        unique=False,
    )

    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("byte_start", sa.Integer(), nullable=False),
        sa.Column("byte_end", sa.Integer(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
    )
    op.create_index(
        op.f("ix_document_chunks_content_hash"),
        "document_chunks",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_chunks_document_id"),
        "document_chunks",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector_index_name", sa.String(length=128), nullable=False),
        sa.Column("vector_id", sa.UUID(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_chunk_embeddings_chunk_id_document_chunks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunk_embeddings")),
        sa.UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            "vector_index_name",
            name="uq_chunk_embeddings_chunk_id_provider_model_vector_index_name",
        ),
    )
    op.create_index(
        op.f("ix_chunk_embeddings_chunk_id"),
        "chunk_embeddings",
        ["chunk_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chunk_embeddings_model"),
        "chunk_embeddings",
        ["model"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chunk_embeddings_provider"),
        "chunk_embeddings",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chunk_embeddings_vector_index_name"),
        "chunk_embeddings",
        ["vector_index_name"],
        unique=False,
    )


def downgrade() -> None:
    _drop_index_if_exists("ix_chunk_embeddings_vector_index_name")
    _drop_index_if_exists("ix_chunk_embeddings_provider")
    _drop_index_if_exists("ix_chunk_embeddings_model")
    _drop_index_if_exists("ix_chunk_embeddings_chunk_id")
    _drop_table_if_exists("chunk_embeddings")

    _drop_index_if_exists("ix_document_chunks_document_id")
    _drop_index_if_exists("ix_document_chunks_content_hash")
    _drop_table_if_exists("document_chunks")

    _drop_index_if_exists("ix_documents_source")
    _drop_index_if_exists("ix_documents_request_id")
    _drop_index_if_exists("ix_documents_content_hash")
    _drop_table_if_exists("documents")
