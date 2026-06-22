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

  // Read-only: this PR does not wire new approve/reject controls to the
  // eligibility section itself (the section has no onClick/button of its
  // own — only the pre-existing, unrelated case-level approve/guide/
  // escalate controls remain, untouched).
  ok(!source.includes('approveEligibility'));
  ok(!source.includes('rejectEligibility'));
});

test('Case Approvals Inbox queue list surfaces verdict and remedy at a glance', () => {
  const source = readText(CASE_APPROVALS_INBOX_TSX);

  ok(source.includes('function CaseCard'));
  ok(source.includes('eligibility && <VerdictBadge'));
  ok(source.includes('eligibility.recommendedRemedy'));
});
