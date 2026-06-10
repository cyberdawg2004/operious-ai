import { test } from 'node:test';
import { deepStrictEqual, ok } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText } from './util.js';

/**
 * The pinned API surface.
 *
 * Adding or removing an endpoint group is a deliberate change. This test
 * asserts the exact set of top-level keys exported under `ENDPOINT` so a
 * silent rename or accidental removal fails CI.
 */
test('ENDPOINT exposes exactly the pinned substrate groups', () => {
  const text = readText(join(ROOT, 'packages', 'contracts', 'src', 'endpoints.ts'));
  const m = text.match(/export const ENDPOINT\s*=\s*\{([\s\S]*?)\}\s*as\s+const/);
  if (!m) throw new Error('cannot locate ENDPOINT object');
  const body = m[1];
  const groups: string[] = [];
  for (const line of body.split('\n')) {
    const v = line.match(/^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*\{/);
    if (v) groups.push(v[1]);
  }
  groups.sort();
  deepStrictEqual(groups, [
    'auth',
    'cognition',
    'governance',
    'operations',
    'tenant',
    'topology',
    'traces',
  ]);
});

test('Command Center queue status accepts null oldest age for empty queues', () => {
  const text = readText(join(ROOT, 'apps', 'command-center2', 'frontend', 'lib', 'api.ts'));

  ok(
    text.includes('oldest_age_seconds: number | null;'),
    'QueueDepthItem.oldest_age_seconds must accept null for empty queues'
  );
});
