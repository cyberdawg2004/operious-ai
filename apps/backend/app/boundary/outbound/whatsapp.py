"""WhatsApp Cloud API sender boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.core.http import get_shared_http_client

_MAX_ERROR_BODY_CHARS = 2048


@dataclass(frozen=True, slots=True)
class WhatsAppTextMessageRequest:
    graph_api_base_url: str
    graph_api_version: str
    phone_number_id: str
    access_token: str
    recipient_phone_number: str
    body: str
    timeout_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class WhatsAppTextMessageResponse:
    provider_message_id: str
    status_code: int


class WhatsAppHTTPResponseProtocol(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class WhatsAppHTTPClientProtocol(Protocol):
    async def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: float,
    ) -> WhatsAppHTTPResponseProtocol: ...


class WhatsAppGraphAPIError(RuntimeError):
    """Raised when the WhatsApp Graph API refuses a message send."""

    def __init__(self, *, status_code: int, response_body: str) -> None:
        super().__init__(f"whatsapp graph api returned {status_code}")
        self.status_code = status_code
        self.response_body = response_body[:_MAX_ERROR_BODY_CHARS]


class WhatsAppGraphSender:
    """Serialize and POST an already-authorized WhatsApp text reply."""

    def __init__(
        self,
        *,
        client: WhatsAppHTTPClientProtocol | None = None,
    ) -> None:
        self._client = client

    async def send_text_message(
        self,
        request: WhatsAppTextMessageRequest,
    ) -> WhatsAppTextMessageResponse:
        client = self._client or get_shared_http_client()
        response = await client.post(
            _messages_url(
                base_url=request.graph_api_base_url,
                version=request.graph_api_version,
                phone_number_id=request.phone_number_id,
            ),
            json=_text_payload(request),
            headers={
                "Authorization": f"Bearer {request.access_token}",
                "Content-Type": "application/json",
            },
            timeout=request.timeout_seconds,
        )
        if not 200 <= response.status_code < 300:
            raise WhatsAppGraphAPIError(
                status_code=response.status_code,
                response_body=response.text,
            )
        return WhatsAppTextMessageResponse(
            provider_message_id=_provider_message_id(response.json()),
            status_code=response.status_code,
        )


def _messages_url(
    *,
    base_url: str,
    version: str,
    phone_number_id: str,
) -> str:
    return "/".join(
        (
            base_url.rstrip("/"),
            version.strip("/"),
            phone_number_id.strip("/"),
            "messages",
        )
    )


def _text_payload(
    request: WhatsAppTextMessageRequest,
) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": request.recipient_phone_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": request.body,
        },
    }


def _provider_message_id(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise WhatsAppGraphAPIError(status_code=502, response_body="malformed_json")
    typed = cast(Mapping[str, Any], payload)
    messages_value = typed.get("messages")
    if not isinstance(messages_value, list) or not messages_value:
        raise WhatsAppGraphAPIError(
            status_code=502,
            response_body="missing_provider_message_id",
        )
    first_value = cast(list[Any], messages_value)[0]
    if not isinstance(first_value, Mapping):
        raise WhatsAppGraphAPIError(
            status_code=502,
            response_body="missing_provider_message_id",
        )
    first = cast(Mapping[str, Any], first_value)
    message_id = first.get("id")
    if not isinstance(message_id, str) or not message_id.strip():
        raise WhatsAppGraphAPIError(
            status_code=502,
            response_body="missing_provider_message_id",
        )
    return message_id.strip()


__all__ = [
    "WhatsAppGraphAPIError",
    "WhatsAppGraphSender",
    "WhatsAppHTTPClientProtocol",
    "WhatsAppTextMessageRequest",
    "WhatsAppTextMessageResponse",
]
