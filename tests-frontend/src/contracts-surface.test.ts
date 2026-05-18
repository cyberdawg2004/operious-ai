import { test } from 'node:test';
import { deepStrictEqual } from 'node:assert';
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
    'cognition',
    'governance',
    'operations',
    'topology',
    'traces',
  ]);
});
