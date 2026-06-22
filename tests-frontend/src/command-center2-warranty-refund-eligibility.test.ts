import { test } from 'node:test';
import { ok } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText } from './util.js';

const CASE_APPROVALS_INBOX_TSX = join(
  ROOT,
  'apps',
  'command-center2',
  'frontend',
  'components',
  'case-approvals-inbox.tsx',
);

test('Case Approvals Inbox renders the W1-W3 grounding/evidence trail readably', () => {
  const source = readText(CASE_APPROVALS_INBOX_TSX);

  // Parses the embedded determination, not a raw JSON dump on screen.
  ok(source.includes('function warrantyRefundEligibility'));
  ok(source.includes('warranty_refund_eligibility'));
  ok(source.includes('function parseGrounding'));

  // The verdict and each grounded check render as readable elements, not
  // a stringified object — name, evidence field/value/confidence, and the
  // rule are each surfaced individually.
  ok(source.includes('function VerdictBadge'));
  ok(source.includes('function GroundingCheckRow'));
  ok(source.includes('check.evidenceField'));
  ok(source.includes('check.evidenceValue'));
  ok(source.includes('check.evidenceConfidence'));
  ok(source.includes('check.rule'));

  // Honest states: ineligible cases show their grounded denial, and
  // cannot_determine cases show what evidence is missing — neither is
  // silently hidden.
  ok(source.includes("eligibility.verdict === \"ineligible\""));
  ok(source.includes("eligibility.verdict === \"cannot_determine\""));
  ok(source.includes('eligibility.missingEvidence'));

  // Availability is never implied as confirmed when W3 could not confirm
  // it — "unconfirmed" renders as its own distinct state, not "available".
  ok(source.includes('function AvailabilityBadge'));
  ok(source.includes("'unconfirmed'") || source.includes('"unconfirmed"'));
  ok(source.includes('Availability unconfirmed'));
});

test('Case Approvals Inbox queue list surfaces verdict and remedy at a glance', () => {
  const source = readText(CASE_APPROVALS_INBOX_TSX);

  ok(source.includes('function CaseCard'));
  ok(source.includes('eligibility && <VerdictBadge'));
  ok(source.includes('eligibility.recommendedRemedy'));
});

test('Reject control exists, is scoped to determinable verdicts, and is capability-gated', () => {
  const source = readText(CASE_APPROVALS_INBOX_TSX);

  // The reject control is wired through the same API client + service
  // call as every other disposition — no parallel execution path.
  ok(source.includes('rejectCaseApproval'));
  ok(source.includes('const runReject'));
  ok(source.includes('onReject={runReject}') || source.includes('onReject={'));

  // Capability gate: showReject requires canApprove (same capability as
  // approve, mirroring the backend's require_tenant_actions_approve gate
  // on /reject) AND isAwaiting — never rendered for a case that's already
  // resolved (no double-action) or for a session lacking the capability.
  ok(source.includes('const showReject ='));
  ok(source.includes('canApprove &&\n    isAwaiting'));

  // Scoped to determinable verdicts only: a cannot_determine case has
  // nothing to reject yet (missing evidence, not a denial).
  ok(source.includes('eligibility.verdict !== "cannot_determine"'));
});

test('Reject confirm panel never claims a connector fires or a reply is delivered', () => {
  const source = readText(CASE_APPROVALS_INBOX_TSX);

  ok(source.includes('mode === "reject" && showReject'));
  ok(source.includes('Confirm rejection'));
  // The copy explicitly states the negative — no connector, no delivery —
  // rather than merely omitting a positive claim, so a reviewer cannot
  // mistake silence for confirmation.
  ok(source.includes('denying</strong> this recommendation'));
  ok(source.includes('connector fires'));
  ok(source.includes('not</strong> delivered'));
  ok(source.includes('its bound action is denied too'));
});
