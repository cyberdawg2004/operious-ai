# Phase 6-F Demo Walkthrough: Anker Pilot

Audience: Jiao Ma or an Anker stakeholder evaluating whether Operious can
process real support tickets with governance and forensic traceability.

## Pre-Call Setup

1. Run the seed script against production with Anker pilot credentials.
2. Confirm all five tickets return `session_id` values.
3. Open Command Center at `https://app.operious.com`.
4. Sign in through Auth0.
5. Confirm Operations Queue is filtered to tenant `anker-pilot`.

## Talk Track

### 1. Operations Queue

Say: "This is not sample UI data. These are sessions created by the live
ingress and dispatch pipeline for the Anker pilot tenant."

Click the `charging-allow` session.

What it proves:

- Real session row from `/api/v1/session/sessions`.
- Tenant-scoped data surface.
- Event count comes from the session sequence head.

### 2. Trace Inspector

Say: "Every screen here is backed by the canonical session timeline. We
can replay what entered the boundary, what governance admitted, what
diagnostic execution ran, and what the agent concluded."

Open the timeline payload for `diagnostic_analysis_completed`.

What it proves:

- Real events from `/api/v1/session/{session_id}/timeline`.
- Causality detail from `/api/v1/session/sessions/{session_id}/events`.
- Diagnostic category and confidence are auditable.

### 3. Charging Allow Ticket

Narrative:

"The customer has a recent purchase, a clear charging symptom, and no
safety signal. Operious classifies the issue as charging-related and the
governance posture is routine handling."

Expected stakeholder takeaway:

- Common support tickets can be handled without losing policy evidence.

### 4. Refund Denial With Escalation

Open the refund-over-limit session.

Narrative:

"This ticket asks for a refund outside the return posture, lacks required
packaging/accessories, and includes a chargeback threat. Operious should
not auto-grant it. The correct behavior is deny automatic refund handling
and escalate to governance review."

Expected stakeholder takeaway:

- Operious protects Anker from costly, policy-invalid automatic refunds.

### 5. Arabic-Language Ticket

Open the Arabic-language session.

Narrative:

"This reproduces the support-language gap observed in the existing
operation. The issue still appears charging-related, but the language and
safety terms require a multilingual support handoff instead of a brittle
English-only answer."

Expected stakeholder takeaway:

- Operious can expose multilingual gaps as operational events rather than
  hiding them inside agent uncertainty.

### 6. Product Defect Claim

Open the product-defect session.

Narrative:

"The customer provides a serial-ready defect description and video
evidence. Operious classifies the defect and collects warranty evidence
without promising refund terms that require human or policy review."

Expected stakeholder takeaway:

- The system separates evidence collection from final commercial decision.

### 7. Ambiguous Human Review

Open the ambiguous session.

Narrative:

"Here the right answer is restraint. The customer has no proof, no clear
symptom, and no purchase path. Operious should ask for missing evidence or
send the case to review rather than inventing certainty."

Expected stakeholder takeaway:

- Operious is designed to halt or review when evidence is weak.

## Close

Say: "The important part is not only that Operious can answer tickets. It
can show why it answered, which tenant policy it used, and what happened
at every step of the pipeline."

## Evidence To Capture

- Operations Queue with all five sessions.
- Trace Inspector timeline for the charging allow ticket.
- Timeline payload showing diagnostic classification.
- Governance decision ID or admission trace on at least one ticket.
- Knowledge Base showing the five Anker pilot SOP documents.

