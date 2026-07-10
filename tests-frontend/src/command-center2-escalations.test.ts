import { ok, strictEqual } from 'node:assert';
import { test } from 'node:test';
import { join } from 'node:path';
import { ROOT, readText } from './util.js';

const ESCALATIONS_INBOX_TSX = join(
  ROOT,
  'apps',
  'command-center2',
  'frontend',
  'components',
  'escalations-inbox.tsx',
);

const API_TS = join(
  ROOT,
  'apps',
  'command-center2',
  'frontend',
  'lib',
  'api.ts',
);

test('Override and Uphold escalation flows use an explicit review step before the real POST', () => {
  const source = readText(ESCALATIONS_INBOX_TSX);

  ok(source.includes('Review override'));
  ok(source.includes('Review denial'));
  ok(source.includes('Override DENY now'));
  ok(source.includes('Uphold DENY now'));
  ok(source.includes('approveEscalation('));
  ok(source.includes('rejectEscalation('));
  ok(
    source.includes('Choose a path below. The next step asks you to confirm before'),
    'the first-step buttons must explain that they open a confirmation step',
  );
});

test('successful escalation resolutions optimistically disappear from the pending UI', () => {
  const source = readText(ESCALATIONS_INBOX_TSX);

  ok(source.includes('const [resolvedEscalationIds, setResolvedEscalationIds]'));
  ok(source.includes('.filter('));
  ok(source.includes('!resolvedEscalationIds.has(item.escalation_id)'));
  ok(source.includes('Escalation approved and removed from the pending queue.'));
  ok(source.includes('Escalation rejected and removed from the pending queue.'));
});

test('escalation API failures are surfaced with escalation-specific messages', () => {
  const source = readText(API_TS);

  ok(source.includes('escalation_not_found'));
  ok(source.includes('This escalation could not be found.'));
  ok(source.includes('escalation_not_resolvable'));
  ok(source.includes('already resolved or can no longer be changed'));
  ok(source.includes('escalation_approval_failed'));
  ok(source.includes('The override could not be recorded.'));
  ok(source.includes('escalation_rejection_failed'));
  ok(source.includes('The denial could not be upheld.'));
});

test('the live escalation routes still target the real backend approve/reject endpoints', () => {
  const source = readText(API_TS);

  strictEqual(
    source.includes('`/escalations/${encodeURIComponent(escalationId)}/approve`'),
    true,
  );
  strictEqual(
    source.includes('`/escalations/${encodeURIComponent(escalationId)}/reject`'),
    true,
  );
});
