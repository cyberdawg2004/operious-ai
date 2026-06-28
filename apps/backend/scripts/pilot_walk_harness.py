#!/usr/bin/env python
"""Pilot-readiness walk injection harness.

Re-runs the manual pilot-readiness walk (scenarios 1-9) as ONE command
against the REAL deployed pipeline, instead of manually emailing tickets
through the real SES address each time. This is the standing regression
harness for every future change to extraction/eligibility/governance/
autonomy/delivery -- run it after any change that touches that path.

FAITHFULNESS, stated plainly: this injects at the same internal call the
real SES->SNS->webhook delivery makes
(TicketIngressService.process_channel_webhook), using the SAME, real,
unmodified production service object -- constructed via the SAME factory
(get_ticket_ingress_service) the FastAPI route itself uses, against the
real Neon database, the real tenant config, and the real Celery dispatch
queue (Amazon MQ). Diagnostic, eligibility, grounding, governance,
autonomy, and delivery all run as real, unmodified code -- nothing in
that path is mocked, stubbed, or shortcut.

The ONE thing this cannot reproduce is AWS's SNS message signature --
forging it would require AWS's private signing key, which this harness
correctly does not have. The signature-verification step
(SnsMessageVerifier.verify) is the one swapped seam: a fake verifier
returns a successful SnsVerifiedMessage wrapping a REAL, freshly-built
RFC 5322 MIME email (constructed with Python's stdlib email module, the
exact shape parse_email_mime() parses from a genuine SES delivery) instead
of doing RSA signature verification against an AWS certificate. Every
other line `process_channel_webhook` executes -- topic/tenant resolution,
MIME parsing, attachment persistence, BoundaryIngressRuntime ingestion,
dispatch enqueue -- is the real, unmodified call.

SAFETY: every injected ticket's email "From" address is the operator's
own already-used test inbox (resolved from a prior real test delivery, or
passed via --test-recipient), so if a scenario reaches SEND_ELIGIBLE and
genuinely transmits via SES, it can only land in that inbox -- never a
real external customer. Subject and body both carry
pilot_walk_scenarios.PILOT_WALK_TEST_MARKER, so injected tickets are
trivially greppable/filterable and immediately recognizable as test
traffic if one ever lands in an inbox. Each run generates a fresh unique
Message-ID, so the webhook freshness-nonce table naturally de-duplicates
nothing across runs -- idempotent and re-runnable by construction.

Usage:
    python scripts/pilot_walk_harness.py --scenarios 1,3,5,6,7,9
    python scripts/pilot_walk_harness.py --scenarios all --tenant-id anker-pilot
    python scripts/pilot_walk_harness.py --scenarios 1 --test-recipient you@operious.com

Must run inside the deployed backend environment (same process as the
real app: `fly ssh console -a operious-ai-imad -C "python scripts/pilot_walk_harness.py ..."`),
since it imports app.main (which builds the real, fully-wired FastAPI app)
and needs the real DATABASE_URL/Celery broker configured there.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

sys.path.insert(0, "/app")

from pilot_walk_scenarios import (  # noqa: E402
    PILOT_WALK_TEST_MARKER,
    WalkScenario,
    all_scenarios,
    scenario_by_id,
)

_POLL_INTERVAL_SECONDS = 3.0
_DEFAULT_POLL_TIMEOUT_SECONDS = 90.0
_EMAIL_CHANNEL_TYPE = "email"


@dataclass(slots=True)
class ScenarioDisposition:
    scenario: WalkScenario
    injection_ok: bool
    injection_error: str | None = None
    ingress_id: str | None = None
    proposal_id: str | None = None
    resolution_category: str | None = None
    confidence: float | None = None
    status: str | None = None
    autonomy_decision: str | None = None
    governance_verdict: str | None = None
    supervisor_verdict: str | None = None
    grounding_rule_id: str | None = None
    landing_surface: str = "UNPROVEN (no disposition observed within timeout)"
    email_sent: bool = False


class _FakeSnsVerifiedMessage:
    """Duck-types app.boundary.adapters.email_ses.SnsVerifiedMessage."""

    def __init__(self, *, message_id: str, topic_arn: str, message: str) -> None:
        self.message_type = "Notification"
        self.message_id = message_id
        self.topic_arn = topic_arn
        self.timestamp = datetime.now(timezone.utc)
        self.message = message
        self.subscribe_url = None


class _FakeSnsMessageVerifier:
    """The one swapped seam: real SNS signature verification requires AWS's
    private signing key, which a test harness correctly cannot have. This
    duck-types SnsMessageVerifier.verify's exact interface and returns a
    successful verification wrapping the real MIME text the harness built,
    instead of doing RSA verification against a fetched AWS certificate.
    Every other step process_channel_webhook executes is real and
    unmodified.
    """

    def __init__(self, *, mime_text: str, message_id: str) -> None:
        self._mime_text = mime_text
        self._message_id = message_id

    async def verify(
        self, *, payload: dict[str, Any], expected_topic_arn: str
    ) -> _FakeSnsVerifiedMessage:
        return _FakeSnsVerifiedMessage(
            message_id=self._message_id,
            topic_arn=expected_topic_arn,
            message=self._mime_text,
        )


def _build_mime_email(
    *,
    scenario: WalkScenario,
    from_address: str,
    to_address: str,
    message_id: str,
) -> str:
    """A real RFC 5322 MIME message -- the exact shape
    app.boundary.adapters.email_ses.parse_email_mime parses from a genuine
    SES delivery. Built with the stdlib email module, not hand-assembled
    text, so header encoding/MIME boundaries are exactly as a real mail
    transfer agent would produce them.
    """
    msg = EmailMessage()
    msg["From"] = from_address
    msg["To"] = to_address
    msg["Subject"] = scenario.subject
    msg["Message-ID"] = f"<{message_id}@pilot-walk-harness>"
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content(scenario.body)
    for attachment in scenario.attachments:
        maintype, _, subtype = attachment.content_type.partition("/")
        msg.add_attachment(
            attachment.raw_bytes,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=attachment.filename,
        )
    return msg.as_string()


async def _resolve_email_channel(
    *, session: Any, tenant_id: str
) -> tuple[str, str]:
    """Returns (routing_address, webhook_secret). webhook_secret stores
    the SNS Topic ARN for SES-routed tenants -- treated like a credential
    (never logged/printed), read fresh from the DB each run."""
    from sqlalchemy import text

    row = (
        await session.execute(
            text(
                "select routing_address, webhook_secret from "
                "tenant_channel_configurations where tenant_id=:t "
                "and channel_type='email' and status='active'"
            ),
            {"t": tenant_id},
        )
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"no active email channel configured for tenant_id={tenant_id!r}"
        )
    routing_address, webhook_secret = row
    if not webhook_secret:
        raise RuntimeError(
            "email channel has no webhook_secret (SNS topic ARN) configured "
            "-- cannot construct a routable synthetic SNS envelope"
        )
    return routing_address, webhook_secret


async def _resolve_test_recipient(*, session: Any, tenant_id: str) -> str:
    """Default test recipient: the address from the most recent REAL
    delivery to an @operious.com address for this tenant -- i.e. an
    address already proven to be the operator's own test inbox, not a
    customer's. Never falls back to a customer address."""
    from sqlalchemy import text

    row = (
        await session.execute(
            text(
                "select recipient_email_address from "
                "email_customer_reply_deliveries where tenant_id=:t "
                "and recipient_email_address like '%@operious.com' "
                "order by created_at desc limit 1"
            ),
            {"t": tenant_id},
        )
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError(
            "could not auto-resolve a safe test recipient (no prior "
            "@operious.com delivery found for this tenant) -- pass "
            "--test-recipient explicitly"
        )
    return row[0]


async def _build_ingress_service(*, session: Any, app: Any) -> Any:
    """The real TicketIngressService, built by the REAL factory the
    FastAPI route uses -- get_ticket_ingress_service is a plain function
    (FastAPI's Depends() is just a default-value marker), so calling it
    directly with an explicit session and a minimal request-shaped object
    runs the identical construction logic, zero re-derivation risk."""
    from typing import cast

    from fastapi import Request

    from app.dependencies.services import get_ticket_ingress_service

    class _FakeRequest:
        def __init__(self, app: Any) -> None:
            self.app = app

    return get_ticket_ingress_service(
        request=cast(Request, _FakeRequest(app)), session=session
    )


async def _inject_scenario(
    *,
    scenario: WalkScenario,
    tenant_id: str,
    routing_address: str,
    webhook_secret: str,
    test_recipient: str,
    app: Any,
) -> ScenarioDisposition:
    from app.db.session import get_session_factory
    from app.services.ticket_ingress_service import (
        TicketIngressRejected,
        TicketIngressServiceError,
        WebhookDuplicateDeliveryResult,
    )

    disposition = ScenarioDisposition(scenario=scenario, injection_ok=False)
    message_id = f"pilot-walk-{scenario.scenario_id}-{uuid.uuid4().hex}"
    mime_text = _build_mime_email(
        scenario=scenario,
        from_address=test_recipient,
        to_address=routing_address,
        message_id=message_id,
    )
    sns_body = {
        "Type": "Notification",
        "TopicArn": webhook_secret,
        "MessageId": message_id,
        "Timestamp": datetime.now(timezone.utc).isoformat(),
        "Message": mime_text,
        # Placeholder fields a real SNS envelope carries; the fake
        # verifier never inspects these (see _FakeSnsMessageVerifier).
        "SigningCertURL": "https://sns.us-east-1.amazonaws.com/pilot-walk-harness-placeholder.pem",
        "Signature": "pilot-walk-harness-placeholder",
        "SignatureVersion": "1",
    }

    session_factory = get_session_factory()
    async with session_factory() as session:
        service = await _build_ingress_service(session=session, app=app)
        service._sns_message_verifier = _FakeSnsMessageVerifier(  # noqa: SLF001
            mime_text=mime_text, message_id=message_id
        )
        try:
            result = await service.process_channel_webhook(
                channel_type=_EMAIL_CHANNEL_TYPE,
                body=sns_body,
                headers={},
                raw_body=None,
                content_type="application/json",
                tenant_hint=tenant_id,
                request_path="/api/v1/channels/email/webhook",
            )
        except (TicketIngressRejected, TicketIngressServiceError) as exc:
            disposition.injection_error = f"{type(exc).__name__}: {exc}"
            return disposition
        if isinstance(result, WebhookDuplicateDeliveryResult):
            disposition.injection_error = (
                "unexpected duplicate-delivery (nonce collision) -- "
                "should never happen with a fresh message_id"
            )
            return disposition
        disposition.injection_ok = True
        disposition.ingress_id = result.ingress_id
    return disposition


async def _poll_disposition(
    *,
    disposition: ScenarioDisposition,
    tenant_id: str,
    injected_at: datetime,
    poll_timeout_seconds: float,
) -> None:
    from app.db.session import get_owner_session_factory
    from sqlalchemy import text

    session_factory = get_owner_session_factory()
    deadline = asyncio.get_event_loop().time() + poll_timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        async with session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "select proposal_id, resolution_category, confidence, "
                        "status, autonomy_decision, governance_verdict, "
                        "supervisor_verdict, governance_decision_id "
                        "from resolution_proposals where tenant_id=:t "
                        "and created_at > :since order by created_at desc limit 1"
                    ),
                    {"t": tenant_id, "since": injected_at},
                )
            ).fetchone()
            if row is not None:
                (
                    proposal_id,
                    category,
                    confidence,
                    status,
                    autonomy_decision,
                    governance_verdict,
                    supervisor_verdict,
                    governance_decision_id,
                ) = row
                disposition.proposal_id = str(proposal_id)
                disposition.resolution_category = category
                disposition.confidence = confidence
                disposition.status = status
                disposition.autonomy_decision = autonomy_decision
                disposition.governance_verdict = governance_verdict
                disposition.supervisor_verdict = supervisor_verdict
                if governance_decision_id is not None:
                    decision_row = (
                        await session.execute(
                            text(
                                "select evaluated_rules from governance_decisions "
                                "where decision_id=:d"
                            ),
                            {"d": str(governance_decision_id)},
                        )
                    ).fetchone()
                    if decision_row is not None and decision_row[0]:
                        for rule in decision_row[0]:
                            if rule.get("policy_name") == "resolution.grounding":
                                disposition.grounding_rule_id = rule.get("rule_id")
                                break
                case_row = (
                    await session.execute(
                        text(
                            "select status from case_approval_records "
                            "where resolution_proposal_id=:p limit 1"
                        ),
                        {"p": str(proposal_id)},
                    )
                ).fetchone()
                escalation_row = (
                    await session.execute(
                        text(
                            "select reason, priority from escalation_records "
                            "where session_id=(select session_id from "
                            "resolution_proposals where proposal_id=:p) "
                            "order by created_at desc limit 1"
                        ),
                        {"p": str(proposal_id)},
                    )
                ).fetchone()
                delivery_row = (
                    await session.execute(
                        text(
                            "select status from email_customer_reply_deliveries "
                            "where proposal_id=:p limit 1"
                        ),
                        {"p": str(proposal_id)},
                    )
                ).fetchone()
                if delivery_row is not None and delivery_row[0] == "sent":
                    disposition.email_sent = True
                    disposition.landing_surface = "SENT (email delivered)"
                elif case_row is not None:
                    disposition.landing_surface = (
                        f"case_approval_records (status={case_row[0]})"
                    )
                elif escalation_row is not None:
                    disposition.landing_surface = (
                        f"escalation_records (reason={escalation_row[0]!r}, "
                        f"priority={escalation_row[1]})"
                    )
                elif status == "send_eligible":
                    disposition.landing_surface = (
                        "SEND_ELIGIBLE (outbound draft pending delivery worker)"
                    )
                else:
                    disposition.landing_surface = f"status={status}, no queue row yet"
                return
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def _print_report(dispositions: list[ScenarioDisposition]) -> None:
    print()
    print("=" * 100)
    print("PILOT-READINESS WALK -- DISPOSITION MAP")
    print("=" * 100)
    for d in dispositions:
        print(f"\nScenario {d.scenario.scenario_id}: {d.scenario.name}")
        print(f"  expected:  {d.scenario.expected_disposition}")
        if not d.injection_ok:
            print(f"  INJECTION FAILED: {d.injection_error}")
            continue
        print(f"  category:  {d.resolution_category}  confidence={d.confidence}")
        print(
            f"  status={d.status}  autonomy={d.autonomy_decision}  "
            f"governance={d.governance_verdict}  supervisor={d.supervisor_verdict}"
        )
        if d.grounding_rule_id:
            print(f"  grounding rule: {d.grounding_rule_id}")
        print(f"  landing surface: {d.landing_surface}")
    print()
    print("=" * 100)


async def _run(args: argparse.Namespace) -> int:
    from app.main import app
    from app.db.session import get_owner_session_factory

    if args.scenarios.strip().lower() == "all":
        scenarios = list(all_scenarios())
    else:
        ids = [int(s.strip()) for s in args.scenarios.split(",") if s.strip()]
        scenarios = [scenario_by_id(i) for i in ids]

    # Owner session for harness-side setup reads only (RLS bypass for
    # admin lookups) -- the actual injected webhook below still runs on
    # the regular session factory, matching the real request path.
    owner_session_factory = get_owner_session_factory()
    async with owner_session_factory() as session:
        routing_address, webhook_secret = await _resolve_email_channel(
            session=session, tenant_id=args.tenant_id
        )
        test_recipient = args.test_recipient or await _resolve_test_recipient(
            session=session, tenant_id=args.tenant_id
        )

    print(f"Injecting {len(scenarios)} scenario(s) for tenant={args.tenant_id!r}")
    print(f"Test marker: {PILOT_WALK_TEST_MARKER}")
    print("Test recipient: <redacted -- an already-used operator test inbox>")

    dispositions: list[ScenarioDisposition] = []
    for scenario in scenarios:
        print(f"\n--- Injecting scenario {scenario.scenario_id} ({scenario.name}) ---")
        injected_at = datetime.now(timezone.utc)
        disposition = await _inject_scenario(
            scenario=scenario,
            tenant_id=args.tenant_id,
            routing_address=routing_address,
            webhook_secret=webhook_secret,
            test_recipient=test_recipient,
            app=app,
        )
        if not disposition.injection_ok:
            print(f"  injection failed: {disposition.injection_error}")
            dispositions.append(disposition)
            continue
        print(f"  injected ok, ingress_id={disposition.ingress_id}")
        print("  polling for disposition...")
        await _poll_disposition(
            disposition=disposition,
            tenant_id=args.tenant_id,
            injected_at=injected_at,
            poll_timeout_seconds=args.poll_timeout,
        )
        dispositions.append(disposition)

    _print_report(dispositions)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenarios",
        default="all",
        help="comma-separated scenario ids (e.g. 1,3,5,6,7,9) or 'all'",
    )
    parser.add_argument("--tenant-id", default="anker-pilot")
    parser.add_argument(
        "--test-recipient",
        default=None,
        help=(
            "email 'From' address for injected tickets. Defaults to the "
            "address from the most recent real @operious.com test "
            "delivery -- never auto-resolves to a customer address."
        ),
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=_DEFAULT_POLL_TIMEOUT_SECONDS,
        help="seconds to wait for each scenario's disposition to appear",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
