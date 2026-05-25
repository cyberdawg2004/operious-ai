from __future__ import annotations

import pytest

from tests.conftest import requires_postgres


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.load
async def test_single_execution_via_runtime(
    committed_burst_seed,
    suppress_semantic_validation,
    suppress_supervisor_enqueue,
) -> None:
    tenant_id = "burst-sanity-tenant"
    await committed_burst_seed["seed_tenant"](tenant_id)
    execution_id = await committed_burst_seed["seed_execution"](tenant_id)

    from app.db.tenant_context import set_current_tenant
    from app.workers.agent_tasks import execute_diagnostic_agent_runtime

    set_current_tenant(tenant_id)
    try:
        result = await execute_diagnostic_agent_runtime(
            execution_id=execution_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        pytest.fail(f"Runtime raised exception: {type(exc).__name__}: {exc}")

    if result is None or (
        isinstance(result, dict)
        and result.get("status") != "completed"
    ):
        import json

        from sqlalchemy import text

        from app.db.session import get_session_factory

        async with get_session_factory()() as session:
            dlq = await session.execute(
                text(
                    """
                    SELECT task_name, reason, metadata
                    FROM dead_letter_tasks
                    WHERE tenant_id = :t
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"t": tenant_id},
            )
            dlq_row = dlq.fetchone()

            events = await session.execute(
                text(
                    """
                    SELECT operational_act, metadata, occurred_at
                    FROM operational_events
                    WHERE tenant_id = :t
                    ORDER BY occurred_at DESC LIMIT 5
                    """
                ),
                {"t": tenant_id},
            )
            event_rows = events.fetchall()

            envelope = await session.execute(
                text(
                    """
                    SELECT payload_body
                    FROM coordination_envelopes
                    WHERE tenant_id = :t
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"t": tenant_id},
            )
            env_row = envelope.fetchone()

        print("\n=== DIAGNOSTIC CAPTURE ===")
        print(f"result: {result!r}")
        if dlq_row:
            meta = (
                dlq_row[2]
                if isinstance(dlq_row[2], dict)
                else json.loads(dlq_row[2])
            )
            print(f"DLQ task: {dlq_row[0]}")
            print(f"DLQ reason: {dlq_row[1]}")
            print(f"error_class: {meta.get('error_class')}")
            print(f"error_message: {meta.get('error_message')}")
            tb = meta.get("last_traceback", "")
            print(f"traceback tail:\n{tb[-800:] if tb else 'none'}")
        else:
            print("DLQ: no record found")
        if event_rows:
            for ev in event_rows:
                print(f"event: {ev[0]} at {ev[2]}")
        else:
            print("events: none found")
        if env_row:
            payload = (
                env_row[0]
                if isinstance(env_row[0], dict)
                else json.loads(env_row[0])
            )
            print(f"envelope payload keys: {list(payload.keys())}")
            print(
                f"envelope payload[:300]: "
                f"{json.dumps(payload)[:300]}"
            )
        else:
            print("envelope: none found")
        print("=== END DIAGNOSTIC ===\n")

    assert isinstance(result, dict) and result.get("status") == "completed", (
        f"Expected status=completed, got {result!r}. "
        f"See diagnostic output above."
    )
