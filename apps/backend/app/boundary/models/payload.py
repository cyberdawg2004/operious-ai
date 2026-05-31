"""Boundary payload value objects.

* `IngressPayload` — UNTRUSTED raw inbound payload as received
                      from the external system. The substrate
                      hands it to an adapter for normalisation;
                      no other layer treats it as authoritative.
* `EgressPayload`  — TRUSTED outbound payload produced by an
                      adapter from a deterministic runtime
                      artifact, ready for handoff to the external
                      system. The substrate does NOT actually
                      transmit it; transmission is the orchestration
                      layer's responsibility OUTSIDE this package.

Both shapes carry the raw `body` plus declarative metadata about
its delivery (HTTP headers, signature material, content-type).
The substrate keeps the raw body intact for replay reconstruction;
adapters are the only layer that interprets it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class IngressPayload:
    """UNTRUSTED raw inbound payload as received from the external system.

    Attributes:
        body:           Raw payload (typically `dict`, sometimes
                         `str` for plain-text webhooks).
        content_type:   Caller-declared content type
                         (``application/json``, ``text/plain``, …).
                         The substrate does not interpret this; it
                         is preserved for adapter use + audit.
        headers:        HTTP-style headers as a mapping. Stored
                         verbatim for replay.
        signature:      Caller-declared signature header content
                         (e.g. ``X-Hub-Signature-256``). Stored
                         verbatim — adapters verify it against
                         their authentication scheme.
        raw_bytes:      Optional raw byte representation for
                         signature verification schemes that
                         require byte-exact body content.
        request_path:   Server-trusted request path the payload was
                         received at (e.g.
                         ``/api/v1/ingress/channels/twilio/webhook``).
                         Used to derive the canonical URL provider
                         signatures are verified against, instead of a
                         client-supplied header (#23).
    """

    body: Any
    content_type: str | None = None
    headers: dict[str, str] = field(default_factory=dict[str, str])
    signature: str | None = None
    raw_bytes: bytes | None = None
    request_path: str | None = None


@dataclass(frozen=True, slots=True)
class EgressPayload:
    """TRUSTED outbound payload produced by an egress adapter.

    Attributes:
        body:         Payload body the external system expects
                       (caller is responsible for shape).
        content_type: Content type the external system expects.
        headers:      Request headers (e.g. auth tokens). The
                       substrate persists these verbatim; secret
                       handling is the orchestration layer's
                       responsibility.
        target_uri:   Where to deliver the payload (URL / queue /
                       channel). The substrate does NOT transmit
                       it.
        method:       Transport verb (``POST``, ``PUT``, …) when
                       relevant.
    """

    body: Any
    content_type: str | None = None
    headers: dict[str, str] = field(default_factory=dict[str, str])
    target_uri: str | None = None
    method: str | None = None


__all__ = ["IngressPayload", "EgressPayload"]
