"""Regression test for the coordination-envelope decryption outlier.

``agent_tasks._prepare_diagnostic_execution`` builds its
``coordination_repo`` from ``PostgresCoordinationPersistence``. The
``canonical_payload.text`` field of a coordination envelope is encrypted
at rest (``"text"`` is in ``_SENSITIVE_JSON_KEYS``), stored as an
``__op_dp__`` field-level-encryption marker dict, not a plain string.

If ``coordination_repo`` is constructed without ``data_protection=``,
``get_envelope`` returns ``payload_body`` with that marker dict still in
place. ``_extract_text`` only treats string values as body text, so the
encrypted marker is silently dropped and only ``subject`` reaches
diagnosis -- the customer's message body never reaches the model.

This test seeds a coordination envelope through the real
``DataProtectionService`` encrypt path (matching the production shape
exactly) and exercises ``_load_dispatch_content`` -- the function
``_prepare_diagnostic_execution`` calls with the ``coordination_repo`` it
builds at the line-509 construction site -- with both repo
constructions side by side.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.coordination.identity import derive_coordination_id, derive_message_id
from app.coordination.persistence import CoordinationRecord
from app.coordination.persistence.postgres import PostgresCoordinationPersistence
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import derive_lineage_id, derive_session_id
from app.session.persistence import PostgresSessionPersistence, SessionRecord
from app.workers.agent_tasks import _load_dispatch_content
from tests.conftest import requires_postgres

_MASTER_KEY = "dispatch-encrypted-text-master-key-material-32-bytes"
_NOW = datetime(2026, 6, 14, tzinfo=timezone.utc)
_RUNTIME_NAMESPACE = uuid.UUID("6c1f7c0a-6c4e-5b6e-8c0a-9a2f9e3b1d4f")

_SUBJECT = "PowerCore not working"
_BODY = (
    "I've tried two different cables and three wall adapters, and the "
    "LED indicator stays off completely."
)


@pytest.mark.asyncio
@requires_postgres
async def test_load_dispatch_content_decrypts_encrypted_canonical_payload_text(
    pg_seed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = f"tenant-dispatch-encrypted-text-{uuid.uuid4()}"
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", _MASTER_KEY)
    monkeypatch.setenv("DATA_PROTECTION_MASTER_KEYS", "")
    monkeypatch.setenv("DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION", "")
    get_settings.cache_clear()

    data_protection = DataProtectionService.from_settings(
        pg_seed_session, get_settings()
    )

    session_id = derive_session_id(
        scope=SessionScope.TENANT.value,
        tenant_id=tenant_id,
        principal_id="principal-test",
        external_handle=f"{tenant_id}:dispatch-encrypted-text",
    )
    dispatch_id = str(
        derive_coordination_id(seed=f"{tenant_id}|dispatch-encrypted-text")
    )

    await PostgresSessionPersistence(pg_seed_session).save_session(
        SessionRecord(
            session_id=session_id,
            scope=SessionScope.TENANT,
            external_handle=f"{tenant_id}:dispatch-encrypted-text",
            tenant_id=tenant_id,
            principal_id="principal-test",
            opened_at=_NOW,
            lifecycle_phase=SessionLifecyclePhase.ACTIVE,
            lifecycle_recorded_at=_NOW,
            lifecycle_reason=None,
            lineage_id=derive_lineage_id(root_session_id=session_id),
            root_session_id=session_id,
            parent_session_id=None,
            ancestor_session_ids=(),
            lineage_depth=0,
            sequence_head=-1,
            revision=1,
        )
    )

    # Write through the encrypting repo -- "text" lands as an __op_dp__
    # marker dict inside canonical_payload, matching production exactly.
    await PostgresCoordinationPersistence(
        pg_seed_session, data_protection=data_protection
    ).record_envelope(
        CoordinationRecord(
            coordination_id=dispatch_id,
            message_id=str(
                derive_message_id(seed=f"{tenant_id}|dispatch-encrypted-text-msg")
            ),
            sender_id="boundary:email",
            recipient_id="agent:diagnostic",
            recipient_kind="agent",
            direction="inbound",
            message_type="ticket",
            priority=5,
            status="dispatched",
            sequence=1,
            runtime_instance_id=str(uuid.uuid5(_RUNTIME_NAMESPACE, tenant_id)),
            correlation_id=dispatch_id,
            parent_coordination_id=None,
            parent_message_id=None,
            in_reply_to=None,
            request_id=dispatch_id,
            tenant_id=tenant_id,
            governance_decision_id=None,
            governance_chain_id=None,
            payload_content_type="application/json",
            payload_schema_version="1",
            payload_body={
                "canonical_payload": {
                    "subject": _SUBJECT,
                    "text": _BODY,
                }
            },
            created_at=_NOW.isoformat(),
            dispatched_at=_NOW.isoformat(),
            tenant_authority_source="test",
        )
    )
    await pg_seed_session.flush()

    # Sanity check: the stored "text" field really is an __op_dp__ marker
    # dict, not a plaintext string -- otherwise this test would not be
    # exercising the encrypted-at-rest shape at all.
    raw = await PostgresCoordinationPersistence(pg_seed_session).get_envelope(
        dispatch_id, expected_tenant_id=tenant_id
    )
    assert raw is not None
    raw_canonical = raw.payload_body["canonical_payload"]
    assert raw_canonical["subject"] == _SUBJECT
    assert isinstance(raw_canonical["text"], dict)
    assert raw_canonical["text"].get("__op_dp__") == "v1"

    session_repo = PostgresSessionPersistence(pg_seed_session)

    # THE FIX (agent_tasks.py:509): coordination_repo constructed WITH
    # data_protection= decrypts "text" back to a plain string, so
    # _extract_text merges subject + body.
    fixed_content = await _load_dispatch_content(
        coordination_repo=PostgresCoordinationPersistence(
            pg_seed_session, data_protection=data_protection
        ),
        session_repo=session_repo,
        dispatch_id=dispatch_id,
        session_id=str(session_id),
        tenant_id=tenant_id,
    )
    assert _SUBJECT in fixed_content.content
    assert "two different cables and three wall adapters" in fixed_content.content
    assert "LED indicator stays off" in fixed_content.content

    # BREAK-CONTROL (pre-509-fix shape): coordination_repo constructed
    # WITHOUT data_protection= leaves "text" as the __op_dp__ marker dict.
    # _extract_text only accepts string body values, so the body is
    # silently dropped and only the subject reaches diagnosis.
    broken_content = await _load_dispatch_content(
        coordination_repo=PostgresCoordinationPersistence(pg_seed_session),
        session_repo=session_repo,
        dispatch_id=dispatch_id,
        session_id=str(session_id),
        tenant_id=tenant_id,
    )
    assert broken_content.content == _SUBJECT
    assert "two different cables and three wall adapters" not in broken_content.content


def test_prepare_diagnostic_execution_supplies_data_protection_to_coordination_repo() -> (
    None
):
    """Static guard for agent_tasks.py:509.

    ``_prepare_diagnostic_execution`` must construct its
    ``PostgresCoordinationPersistence`` with ``data_protection=`` so
    ``get_envelope`` decrypts ``canonical_payload.text`` before
    ``_extract_text`` runs. Reverting the ``data_protection=`` keyword at
    line 509 makes this test fail.
    """

    source = _function_source(
        "app/workers/agent_tasks.py", "_prepare_diagnostic_execution"
    )
    missing = _constructor_calls_missing_data_protection(
        "PostgresCoordinationPersistence", source
    )
    assert not missing


def _function_source(path: str, function_name: str) -> str:
    import ast
    from pathlib import Path

    source_path = Path(__file__).resolve().parents[1] / path
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{function_name} not found in {path}")


def _constructor_calls_missing_data_protection(
    constructor_name: str,
    source: str,
) -> tuple[int, ...]:
    import ast

    tree = ast.parse(source)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != constructor_name:
            continue
        if not any(keyword.arg == "data_protection" for keyword in node.keywords):
            lines.append(node.lineno)
    return tuple(lines)


def teardown_module(_module: object) -> None:
    get_settings.cache_clear()
