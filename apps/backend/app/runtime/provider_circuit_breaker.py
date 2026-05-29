"""Per-tenant/provider circuit breaker for external AI calls."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime.db.models import ProviderCircuitStateRow

_STATE_NAMESPACE = uuid.UUID("a6027b60-38bd-5d2c-bef0-3f6e08aa6f3d")
_DEFAULT_RETRY_BUDGET_PER_MINUTE = 5
_DEFAULT_UNAVAILABLE_FAILURE_THRESHOLD = 3
_DEFAULT_OPEN_SECONDS = 60


class ProviderCircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderFailureKind(StrEnum):
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    TRANSIENT = "transient"


class ProviderCircuitOpenError(RuntimeError):
    """Raised before a provider socket is opened while the circuit is open."""

    def __init__(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        open_until: datetime | None,
        state: ProviderCircuitState = ProviderCircuitState.OPEN,
    ) -> None:
        self.tenant_id = tenant_id
        self.provider_name = provider_name
        self.open_until = open_until
        self.state = state
        suffix = f" until {open_until.isoformat()}" if open_until is not None else ""
        super().__init__(
            f"provider circuit {state.value} for {tenant_id}/{provider_name}{suffix}"
        )


@dataclass(frozen=True, slots=True)
class ProviderCircuitSnapshot:
    state_id: uuid.UUID
    tenant_id: str
    provider_name: str
    state: ProviderCircuitState
    consecutive_failures: int
    retry_count: int
    retry_window_started_at: datetime | None
    opened_at: datetime | None
    open_until: datetime | None
    half_open_trial_started_at: datetime | None
    last_failure_reason: str | None
    last_transition_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def is_open(self) -> bool:
        return self.state is ProviderCircuitState.OPEN


class _Unset:
    pass


_UNSET = _Unset()


class ProviderCircuitBreaker:
    """Stateful circuit breaker keyed by ``(tenant_id, provider_name)``."""

    def __init__(
        self,
        *,
        session: AsyncSession | None = None,
        retry_budget_per_minute: int = _DEFAULT_RETRY_BUDGET_PER_MINUTE,
        unavailable_failure_threshold: int = _DEFAULT_UNAVAILABLE_FAILURE_THRESHOLD,
        default_open_seconds: int = _DEFAULT_OPEN_SECONDS,
        auto_commit: bool = False,
    ) -> None:
        if retry_budget_per_minute < 1:
            raise ValueError("retry_budget_per_minute must be >= 1")
        if unavailable_failure_threshold < 1:
            raise ValueError("unavailable_failure_threshold must be >= 1")
        if default_open_seconds < 1:
            raise ValueError("default_open_seconds must be >= 1")
        self._session = session
        self._retry_budget_per_minute = retry_budget_per_minute
        self._unavailable_failure_threshold = unavailable_failure_threshold
        self._default_open_seconds = default_open_seconds
        self._auto_commit = auto_commit
        self._memory: dict[tuple[str, str], ProviderCircuitSnapshot] = {}

    async def before_request(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        now: datetime | None = None,
    ) -> ProviderCircuitSnapshot:
        """Validate/adapt state before an external provider call."""

        observed_at = _coerce_now(now)
        snapshot = await self.get_state(
            tenant_id=tenant_id,
            provider_name=provider_name,
            now=observed_at,
        )
        if snapshot.state is ProviderCircuitState.OPEN:
            if snapshot.open_until is not None and snapshot.open_until <= observed_at:
                snapshot = await self._transition(
                    snapshot,
                    state=ProviderCircuitState.HALF_OPEN,
                    now=observed_at,
                    half_open_trial_started_at=None,
                    last_failure_reason=None,
                    metadata={**snapshot.metadata, "transition": "cooldown_elapsed"},
                )
            else:
                raise ProviderCircuitOpenError(
                    tenant_id=tenant_id,
                    provider_name=provider_name,
                    open_until=snapshot.open_until,
                    state=snapshot.state,
                )
        if snapshot.state is ProviderCircuitState.HALF_OPEN:
            if snapshot.half_open_trial_started_at is not None:
                raise ProviderCircuitOpenError(
                    tenant_id=tenant_id,
                    provider_name=provider_name,
                    open_until=snapshot.open_until,
                    state=snapshot.state,
                )
            snapshot = await self._transition(
                snapshot,
                state=ProviderCircuitState.HALF_OPEN,
                now=observed_at,
                half_open_trial_started_at=observed_at,
                metadata={**snapshot.metadata, "transition": "half_open_trial"},
            )
        return snapshot

    async def get_state(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        now: datetime | None = None,
    ) -> ProviderCircuitSnapshot:
        observed_at = _coerce_now(now)
        _validate_key(tenant_id=tenant_id, provider_name=provider_name)
        existing = await self._load(tenant_id=tenant_id, provider_name=provider_name)
        if existing is not None:
            return existing
        snapshot = ProviderCircuitSnapshot(
            state_id=_state_id(tenant_id=tenant_id, provider_name=provider_name),
            tenant_id=tenant_id,
            provider_name=provider_name,
            state=ProviderCircuitState.CLOSED,
            consecutive_failures=0,
            retry_count=0,
            retry_window_started_at=None,
            opened_at=None,
            open_until=None,
            half_open_trial_started_at=None,
            last_failure_reason=None,
            last_transition_at=observed_at,
            updated_at=observed_at,
            metadata={"origin": "provider_circuit_breaker"},
        )
        return await self._save(snapshot)

    async def record_success(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        now: datetime | None = None,
    ) -> ProviderCircuitSnapshot:
        observed_at = _coerce_now(now)
        snapshot = await self.get_state(
            tenant_id=tenant_id,
            provider_name=provider_name,
            now=observed_at,
        )
        return await self._transition(
            snapshot,
            state=ProviderCircuitState.CLOSED,
            now=observed_at,
            consecutive_failures=0,
            opened_at=None,
            open_until=None,
            half_open_trial_started_at=None,
            last_failure_reason=None,
            metadata={**snapshot.metadata, "transition": "provider_success"},
        )

    async def record_http_status(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        status_code: int,
        retry_after: str | None = None,
        now: datetime | None = None,
    ) -> ProviderCircuitSnapshot:
        observed_at = _coerce_now(now)
        if status_code == 429:
            open_until = _retry_after_deadline(
                retry_after=retry_after,
                now=observed_at,
                default_seconds=self._default_open_seconds,
            )
            return await self.open(
                tenant_id=tenant_id,
                provider_name=provider_name,
                reason=ProviderFailureKind.RATE_LIMIT.value,
                open_until=open_until,
                now=observed_at,
                metadata={"http_status": status_code, "retry_after": retry_after},
            )
        if status_code in {503, 504}:
            return await self.record_failure(
                tenant_id=tenant_id,
                provider_name=provider_name,
                reason=ProviderFailureKind.UNAVAILABLE.value,
                now=observed_at,
                opens_after_threshold=True,
                metadata={"http_status": status_code},
            )
        if status_code == 408:
            return await self.record_failure(
                tenant_id=tenant_id,
                provider_name=provider_name,
                reason=ProviderFailureKind.TRANSIENT.value,
                now=observed_at,
                opens_after_threshold=True,
                metadata={"http_status": status_code},
            )
        snapshot = await self.get_state(
            tenant_id=tenant_id,
            provider_name=provider_name,
            now=observed_at,
        )
        return snapshot

    async def record_transient_failure(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        reason: str,
        now: datetime | None = None,
    ) -> ProviderCircuitSnapshot:
        observed_at = _coerce_now(now)
        await self.consume_retry_budget(
            tenant_id=tenant_id,
            provider_name=provider_name,
            now=observed_at,
        )
        return await self.record_failure(
            tenant_id=tenant_id,
            provider_name=provider_name,
            reason=reason,
            now=observed_at,
            opens_after_threshold=True,
            metadata={"failure_kind": ProviderFailureKind.TRANSIENT.value},
        )

    async def consume_retry_budget(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        now: datetime | None = None,
    ) -> ProviderCircuitSnapshot:
        observed_at = _coerce_now(now)
        snapshot = await self.get_state(
            tenant_id=tenant_id,
            provider_name=provider_name,
            now=observed_at,
        )
        window_start = snapshot.retry_window_started_at
        if window_start is None or window_start <= observed_at - timedelta(minutes=1):
            window_start = observed_at
            retry_count = 0
        else:
            retry_count = snapshot.retry_count
        retry_count += 1
        updated = _replace(
            snapshot,
            retry_window_started_at=window_start,
            retry_count=retry_count,
            updated_at=observed_at,
            metadata={**snapshot.metadata, "retry_budget": retry_count},
        )
        updated = await self._save(updated)
        if retry_count > self._retry_budget_per_minute:
            return await self.open(
                tenant_id=tenant_id,
                provider_name=provider_name,
                reason="retry_budget_exhausted",
                open_until=observed_at + timedelta(seconds=self._default_open_seconds),
                now=observed_at,
                metadata={"retry_count": retry_count},
            )
        return updated

    async def record_failure(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        reason: str,
        now: datetime | None = None,
        opens_after_threshold: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProviderCircuitSnapshot:
        observed_at = _coerce_now(now)
        snapshot = await self.get_state(
            tenant_id=tenant_id,
            provider_name=provider_name,
            now=observed_at,
        )
        failures = snapshot.consecutive_failures + 1
        if (
            snapshot.state is ProviderCircuitState.HALF_OPEN
            or (
                opens_after_threshold
                and failures >= self._unavailable_failure_threshold
            )
        ):
            return await self.open(
                tenant_id=tenant_id,
                provider_name=provider_name,
                reason=reason,
                open_until=observed_at + timedelta(seconds=self._default_open_seconds),
                now=observed_at,
                metadata={
                    **dict(metadata or {}),
                    "consecutive_failures": failures,
                },
            )
        return await self._transition(
            snapshot,
            state=ProviderCircuitState.CLOSED,
            now=observed_at,
            consecutive_failures=failures,
            last_failure_reason=reason,
            metadata={
                **snapshot.metadata,
                **dict(metadata or {}),
                "transition": "provider_failure",
            },
        )

    async def open(
        self,
        *,
        tenant_id: str,
        provider_name: str,
        reason: str,
        open_until: datetime | None = None,
        now: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProviderCircuitSnapshot:
        observed_at = _coerce_now(now)
        snapshot = await self.get_state(
            tenant_id=tenant_id,
            provider_name=provider_name,
            now=observed_at,
        )
        return await self._transition(
            snapshot,
            state=ProviderCircuitState.OPEN,
            now=observed_at,
            consecutive_failures=max(1, snapshot.consecutive_failures),
            opened_at=observed_at,
            open_until=open_until
            or observed_at + timedelta(seconds=self._default_open_seconds),
            half_open_trial_started_at=None,
            last_failure_reason=reason,
            metadata={
                **snapshot.metadata,
                **dict(metadata or {}),
                "transition": "provider_circuit_open",
            },
        )

    async def _transition(
        self,
        snapshot: ProviderCircuitSnapshot,
        *,
        state: ProviderCircuitState,
        now: datetime,
        consecutive_failures: int | None = None,
        opened_at: datetime | None | _Unset = _UNSET,
        open_until: datetime | None | _Unset = _UNSET,
        half_open_trial_started_at: datetime | None | _Unset = _UNSET,
        last_failure_reason: str | None | _Unset = _UNSET,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProviderCircuitSnapshot:
        return await self._save(
            _replace(
                snapshot,
                state=state,
                consecutive_failures=(
                    snapshot.consecutive_failures
                    if consecutive_failures is None
                    else consecutive_failures
                ),
                opened_at=opened_at,
                open_until=open_until,
                half_open_trial_started_at=half_open_trial_started_at,
                last_failure_reason=last_failure_reason,
                last_transition_at=now,
                updated_at=now,
                metadata=dict(metadata or snapshot.metadata),
            )
        )

    async def _load(
        self,
        *,
        tenant_id: str,
        provider_name: str,
    ) -> ProviderCircuitSnapshot | None:
        if self._session is None:
            return self._memory.get((tenant_id, provider_name))
        row = (
            await self._session.execute(
                select(ProviderCircuitStateRow).where(
                    ProviderCircuitStateRow.tenant_id == tenant_id,
                    ProviderCircuitStateRow.provider_name == provider_name,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return _snapshot_from_row(row)

    async def _save(
        self,
        snapshot: ProviderCircuitSnapshot,
    ) -> ProviderCircuitSnapshot:
        if self._session is None:
            self._memory[(snapshot.tenant_id, snapshot.provider_name)] = snapshot
            return snapshot
        row = (
            await self._session.execute(
                select(ProviderCircuitStateRow).where(
                    ProviderCircuitStateRow.state_id == snapshot.state_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProviderCircuitStateRow(state_id=snapshot.state_id)
            self._session.add(row)
        _apply_snapshot(row, snapshot)
        await self._session.flush()
        if self._auto_commit:
            await self._session.commit()
        return snapshot


def _replace(
    snapshot: ProviderCircuitSnapshot,
    *,
    state: ProviderCircuitState | None = None,
    consecutive_failures: int | None = None,
    retry_count: int | None = None,
    retry_window_started_at: datetime | None | _Unset = _UNSET,
    opened_at: datetime | None | _Unset = _UNSET,
    open_until: datetime | None | _Unset = _UNSET,
    half_open_trial_started_at: datetime | None | _Unset = _UNSET,
    last_failure_reason: str | None | _Unset = _UNSET,
    last_transition_at: datetime | None = None,
    updated_at: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ProviderCircuitSnapshot:
    return ProviderCircuitSnapshot(
        state_id=snapshot.state_id,
        tenant_id=snapshot.tenant_id,
        provider_name=snapshot.provider_name,
        state=state or snapshot.state,
        consecutive_failures=(
            snapshot.consecutive_failures
            if consecutive_failures is None
            else consecutive_failures
        ),
        retry_count=snapshot.retry_count if retry_count is None else retry_count,
        retry_window_started_at=_datetime_or_existing(
            retry_window_started_at,
            snapshot.retry_window_started_at,
        ),
        opened_at=_datetime_or_existing(opened_at, snapshot.opened_at),
        open_until=_datetime_or_existing(open_until, snapshot.open_until),
        half_open_trial_started_at=_datetime_or_existing(
            half_open_trial_started_at,
            snapshot.half_open_trial_started_at,
        ),
        last_failure_reason=_str_or_existing(
            last_failure_reason,
            snapshot.last_failure_reason,
        ),
        last_transition_at=last_transition_at or snapshot.last_transition_at,
        updated_at=updated_at or snapshot.updated_at,
        metadata=dict(metadata or snapshot.metadata),
    )


def _datetime_or_existing(
    value: datetime | None | _Unset,
    existing: datetime | None,
) -> datetime | None:
    if isinstance(value, _Unset):
        return existing
    return value


def _str_or_existing(
    value: str | None | _Unset,
    existing: str | None,
) -> str | None:
    if isinstance(value, _Unset):
        return existing
    return value


def _apply_snapshot(
    row: ProviderCircuitStateRow,
    snapshot: ProviderCircuitSnapshot,
) -> None:
    row.tenant_id = snapshot.tenant_id
    row.provider_name = snapshot.provider_name
    row.state = snapshot.state.value
    row.consecutive_failures = snapshot.consecutive_failures
    row.retry_count = snapshot.retry_count
    row.retry_window_started_at = snapshot.retry_window_started_at
    row.opened_at = snapshot.opened_at
    row.open_until = snapshot.open_until
    row.half_open_trial_started_at = snapshot.half_open_trial_started_at
    row.last_failure_reason = snapshot.last_failure_reason
    row.last_transition_at = snapshot.last_transition_at
    row.updated_at = snapshot.updated_at
    row.metadata_json = dict(snapshot.metadata)


def _snapshot_from_row(row: ProviderCircuitStateRow) -> ProviderCircuitSnapshot:
    return ProviderCircuitSnapshot(
        state_id=row.state_id,
        tenant_id=row.tenant_id,
        provider_name=row.provider_name,
        state=ProviderCircuitState(row.state),
        consecutive_failures=row.consecutive_failures,
        retry_count=row.retry_count,
        retry_window_started_at=row.retry_window_started_at,
        opened_at=row.opened_at,
        open_until=row.open_until,
        half_open_trial_started_at=row.half_open_trial_started_at,
        last_failure_reason=row.last_failure_reason,
        last_transition_at=row.last_transition_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata_json or {}),
    )


def _state_id(*, tenant_id: str, provider_name: str) -> uuid.UUID:
    return uuid.uuid5(_STATE_NAMESPACE, f"{tenant_id}|{provider_name}")


def _validate_key(*, tenant_id: str, provider_name: str) -> None:
    if not tenant_id.strip():
        raise ValueError("tenant_id must be non-empty")
    if not provider_name.strip():
        raise ValueError("provider_name must be non-empty")


def _coerce_now(now: datetime | None) -> datetime:
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        return observed_at.replace(tzinfo=timezone.utc)
    return observed_at


def _retry_after_deadline(
    *,
    retry_after: str | None,
    now: datetime,
    default_seconds: int,
) -> datetime:
    if retry_after is None or not retry_after.strip():
        return now + timedelta(seconds=default_seconds)
    stripped = retry_after.strip()
    try:
        seconds = int(stripped)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(stripped)
        except (TypeError, ValueError):
            return now + timedelta(seconds=default_seconds)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return now + timedelta(seconds=max(0, seconds))


__all__ = [
    "ProviderCircuitBreaker",
    "ProviderCircuitOpenError",
    "ProviderCircuitSnapshot",
    "ProviderCircuitState",
]
