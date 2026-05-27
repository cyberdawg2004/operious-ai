import { test } from 'node:test';
import { ok } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText } from './util.js';

const TRACE_INSPECTOR_TSX = join(
  ROOT,
  'apps',
  'command-center2',
  'frontend',
  'components',
  'trace-inspector.tsx',
);

test('Trace Inspector renders resolution proposal events', () => {
  const source = readText(TRACE_INSPECTOR_TSX);

  ok(source.includes('resolution_proposal_created'));
  ok(source.includes('ResolutionProposalSummary'));
  ok(source.includes('Proposed Customer Reply'));
  ok(source.includes('autonomy_decision'));
  ok(source.includes('supervisor_verdict'));
  ok(source.includes('governance_verdict'));
  ok(source.includes('Recommended Actions'));
  ok(source.includes('event.payload.evidence'));
});

test('Trace Inspector keeps diagnostic citation rendering for old events', () => {
  const source = readText(TRACE_INSPECTOR_TSX);

  ok(source.includes('event.payload.retrieved_citations'));
  ok(source.includes(': event.payload.retrieved_citations'));
  ok(source.includes('KnowledgeSources citations={citations}'));
});
