"""Typed tenant channel self-service payload builders."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.exceptions import TenantConfigurationError
from app.tenant.persistence import TenantChannelConfigurationRecord


@dataclass(frozen=True, slots=True)
class TenantChannelSelfServicePayload:
    channel_type: TenantChannelType
    routing_address: str
    credentials: Mapping[str, Any] | None
    webhook_secret: str | None
    status: TenantChannelStatus
    self_service_config: Mapping[str, Any]
    last_validation_error: str | None
    validation_evidence: Mapping[str, Any]


def build_whatsapp_self_service_payload(
    request: Mapping[str, Any],
    *,
    existing_channel: TenantChannelConfigurationRecord | None = None,
    existing_credentials: Mapping[str, Any] | None = None,
) -> TenantChannelSelfServicePayload:
    phone_number_id = _required_text(request, "phone_number_id", "whatsapp")
    graph_api_version = _text(request, "graph_api_version") or "v25.0"
    existing = dict(existing_credentials or {})
    access_token = (
        _text(request, "access_token")
        or _text(request, "system_user_token")
        or _text(existing, "access_token")
        or _text(existing, "graph_api_access_token")
        or _text(existing, "bearer_token")
    )
    if access_token is None:
        raise TenantConfigurationError(
            "whatsapp access_token is required before credentials can be stored"
        )
    webhook_verify_token = (
        _text(request, "webhook_verify_token")
        or _text(request, "verify_token")
        or _text(existing, "webhook_verify_token")
        or _text(existing, "verify_token")
        or secrets.token_urlsafe(32)
    )
    app_secret = _text(request, "app_secret") or _text(existing, "app_secret")
    credentials = {
        **existing,
        "provider": "meta_whatsapp_manual",
        "access_token": access_token,
        "graph_api_access_token": access_token,
        "phone_number_id": phone_number_id,
        "whatsapp_phone_number_id": phone_number_id,
        "graph_api_version": graph_api_version,
        "webhook_verify_token": webhook_verify_token,
        "verify_token": webhook_verify_token,
    }
    if app_secret is not None:
        credentials["app_secret"] = app_secret
    for key in ("waba_id", "business_account_id", "app_id", "config_id"):
        value = _text(request, key)
        if value is not None:
            credentials[key] = value

    self_service_config = _compact(
        {
            "setup": "manual_token",
            "waba_id": _text(request, "waba_id"),
            "phone_number_id": phone_number_id,
            "business_account_id": _text(request, "business_account_id"),
            "graph_api_version": graph_api_version,
            "app_id": _text(request, "app_id"),
            "config_id": _text(request, "config_id"),
        }
    )
    status, error, evidence = _pending_validation(
        requested_status=_status(request),
        provider="meta_graph",
        mode="manual_token",
    )
    credentials_changed = (
        existing_channel is None
        or _any_text(
            request,
            (
                "access_token",
                "system_user_token",
                "webhook_verify_token",
                "verify_token",
                "app_secret",
            ),
        )
        or _text(existing, "phone_number_id") != phone_number_id
        or _text(existing, "graph_api_version") != graph_api_version
        or (
            _text(existing, "webhook_verify_token") is None
            and _text(existing, "verify_token") is None
        )
    )
    return TenantChannelSelfServicePayload(
        channel_type=TenantChannelType.WHATSAPP,
        routing_address=phone_number_id,
        credentials=credentials if credentials_changed else None,
        webhook_secret=(
            existing_channel.webhook_secret
            if existing_channel is not None
            else secrets.token_urlsafe(32)
        ),
        status=status,
        self_service_config=self_service_config,
        last_validation_error=error,
        validation_evidence=evidence,
    )


def build_ses_self_service_payload(
    request: Mapping[str, Any],
    *,
    existing_channel: TenantChannelConfigurationRecord | None = None,
    existing_credentials: Mapping[str, Any] | None = None,
) -> TenantChannelSelfServicePayload:
    mode = _required_text(request, "mode", "ses")
    if mode not in {"managed", "byo_role", "byo_access_key"}:
        raise TenantConfigurationError(
            "ses mode must be managed, byo_role, or byo_access_key"
        )
    region = _required_text(request, "region", "ses")
    source_email = _text(request, "source_email")
    source_domain = _text(request, "source_domain")
    inbound_address = _text(request, "inbound_address")
    inbound_domain = _text(request, "inbound_domain")
    routing_address = (
        inbound_address
        or source_email
        or inbound_domain
        or source_domain
    )
    if routing_address is None:
        raise TenantConfigurationError(
            "ses source_email, source_domain, inbound_address, or inbound_domain "
            "is required"
        )

    existing = dict(existing_credentials or {})
    self_service_config = _compact(
        {
            "mode": mode,
            "region": region,
            "source_email": source_email,
            "source_domain": source_domain,
            "inbound_address": inbound_address,
            "inbound_domain": inbound_domain,
            "topic_arn": _text(request, "topic_arn"),
            "receipt_rule_set": _text(request, "receipt_rule_set"),
            "receipt_rule_name": _text(request, "receipt_rule_name"),
            "role_arn": _text(request, "role_arn"),
            "external_id": _text(request, "external_id"),
        }
    )
    credentials = {
        **existing,
        "mode": mode,
        "region": region,
        "aws_region": region,
        "ses_region": region,
    }
    if source_email is not None:
        credentials["source_email_address"] = source_email
        credentials["from_email_address"] = source_email
        credentials["ses_source_email_address"] = source_email
    if source_domain is not None:
        credentials["domain"] = source_domain
        credentials["source_domain"] = source_domain
    if inbound_address is not None:
        credentials["inbound_address"] = inbound_address
    if inbound_domain is not None:
        credentials["inbound_domain"] = inbound_domain
    for key in ("topic_arn", "receipt_rule_set", "receipt_rule_name"):
        value = _text(request, key)
        if value is not None:
            credentials[key] = value

    if mode == "managed":
        credentials["provider"] = "aws_ses_managed"
        if source_domain is None and source_email and "@" in source_email:
            credentials["domain"] = source_email.rsplit("@", 1)[1].lower()
    elif mode == "byo_role":
        credentials["provider"] = "aws_ses_byo_role"
        credentials["role_arn"] = _required_text(request, "role_arn", "ses")
        credentials["external_id"] = _required_text(request, "external_id", "ses")
    else:
        credentials["provider"] = "aws_ses_byo_access_key"
        access_key_id = (
            _text(request, "access_key_id")
            or _text(request, "aws_access_key_id")
            or _text(existing, "access_key_id")
            or _text(existing, "aws_access_key_id")
        )
        secret_access_key = (
            _text(request, "secret_access_key")
            or _text(request, "aws_secret_access_key")
            or _text(existing, "secret_access_key")
            or _text(existing, "aws_secret_access_key")
        )
        if access_key_id is None or secret_access_key is None:
            raise TenantConfigurationError(
                "ses access_key_id and secret_access_key are required for "
                "byo_access_key mode"
            )
        credentials["access_key_id"] = access_key_id
        credentials["aws_access_key_id"] = access_key_id
        credentials["secret_access_key"] = secret_access_key
        credentials["aws_secret_access_key"] = secret_access_key
        session_token = (
            _text(request, "session_token")
            or _text(existing, "session_token")
        )
        if session_token is not None:
            credentials["session_token"] = session_token

    status, error, evidence = _pending_validation(
        requested_status=_status(request),
        provider="aws_ses",
        mode=mode,
    )
    topic_arn = _text(request, "topic_arn")
    credentials_changed = (
        existing_channel is None
        or mode != _text(existing, "mode")
        or _any_text(
            request,
            (
                "access_key_id",
                "aws_access_key_id",
                "secret_access_key",
                "aws_secret_access_key",
                "session_token",
            ),
        )
        or _credential_route_changed(existing, credentials)
    )
    return TenantChannelSelfServicePayload(
        channel_type=TenantChannelType.EMAIL,
        routing_address=routing_address,
        credentials=credentials if credentials_changed else None,
        webhook_secret=(
            topic_arn
            or (
                existing_channel.webhook_secret
                if existing_channel is not None
                else secrets.token_urlsafe(32)
            )
        ),
        status=status,
        self_service_config=self_service_config,
        last_validation_error=error,
        validation_evidence=evidence,
    )


def _pending_validation(
    *,
    requested_status: TenantChannelStatus,
    provider: str,
    mode: str,
) -> tuple[TenantChannelStatus, str | None, dict[str, Any]]:
    if requested_status is TenantChannelStatus.DISABLED:
        status = TenantChannelStatus.DISABLED
        error = None
    elif requested_status is TenantChannelStatus.DRAFT:
        status = TenantChannelStatus.DRAFT
        error = None
    else:
        status = (
            TenantChannelStatus.VALIDATION_FAILED
            if requested_status is TenantChannelStatus.VALIDATION_FAILED
            else TenantChannelStatus.PENDING_VALIDATION
        )
        error = "real provider validation evidence is required before activation"
    evidence = {
        "validator": "tenant_self_service",
        "provider": provider,
        "mode": mode,
        "result": "pending_provider_validation",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return status, error, evidence


def _status(request: Mapping[str, Any]) -> TenantChannelStatus:
    raw = str(
        request.get("status") or TenantChannelStatus.PENDING_VALIDATION.value
    )
    status = TenantChannelStatus(raw)
    allowed = {
        TenantChannelStatus.DRAFT,
        TenantChannelStatus.PENDING_VALIDATION,
        TenantChannelStatus.VALIDATION_FAILED,
        TenantChannelStatus.ACTIVE,
        TenantChannelStatus.DISABLED,
    }
    if status not in allowed:
        raise TenantConfigurationError(
            "channel status must be draft, pending_validation, validation_failed, "
            "active, or disabled"
        )
    return status


def _credential_route_changed(
    existing: Mapping[str, Any],
    credentials: Mapping[str, Any],
) -> bool:
    for key in (
        "region",
        "source_email_address",
        "domain",
        "inbound_address",
        "inbound_domain",
        "role_arn",
        "external_id",
        "topic_arn",
        "receipt_rule_set",
        "receipt_rule_name",
    ):
        if _text(existing, key) != _text(credentials, key):
            return True
    return False


def _any_text(value: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    return any(_text(value, key) is not None for key in keys)


def _required_text(
    value: Mapping[str, Any],
    key: str,
    channel: str,
) -> str:
    text = _text(value, key)
    if text is None:
        raise TenantConfigurationError(
            f"{channel} self-service field {key} is required"
        )
    return text


def _text(value: Mapping[str, Any], key: str) -> str | None:
    raw = value.get(key)
    if isinstance(raw, str):
        text = raw.strip()
        return text or None
    return None


def _compact(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


__all__ = [
    "TenantChannelSelfServicePayload",
    "build_ses_self_service_payload",
    "build_whatsapp_self_service_payload",
]
