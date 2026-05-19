"""drop legacy workflow and memory tables"""

from typing import Sequence, Union

from alembic import op


revision: str = "0004_drop_legacy"
down_revision: Union[str, None] = "0003_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("chunk_embeddings")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("task_executions")
    op.drop_table("workflow_executions")


def downgrade() -> None:
    pass
