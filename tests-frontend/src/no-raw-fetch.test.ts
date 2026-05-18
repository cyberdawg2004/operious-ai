import { test } from 'node:test';
import { strictEqual } from 'node:assert';
import { join, relative } from 'node:path';
import { ROOT, readText, tsFilesUnder } from './util.js';

/**
 * Frontend hardening: no raw fetch.
 *
 * UI components MUST go through @operious/sdk hooks. Direct `fetch(` calls
 * are only allowed in:
 *   - packages/sdk/src/client.tsx          (the only allowed transport authority)
 *   - apps/command-center/src/mocks/*.ts   (deterministic mock transport)
 *
 * Any other `fetch(` call is a semantic violation: the UI bypassed the SDK.
 */
const ALLOWED_PATHS = [
  join('packages', 'sdk', 'src', 'client.tsx'),
  join('apps', 'command-center', 'src', 'mocks', 'fetch.ts'),
];

const SCAN_ROOTS = [
  join(ROOT, 'apps', 'marketing', 'src'),
  join(ROOT, 'apps', 'command-center', 'src'),
  join(ROOT, 'packages'),
];

const FETCH_PATTERN = /\bfetch\s*\(/;

test('no UI / package code calls fetch() directly', () => {
  const offences: string[] = [];
  for (const root of SCAN_ROOTS) {
    for (const file of tsFilesUnder(root)) {
      const rel = relative(ROOT, file);
      if (ALLOWED_PATHS.some((allowed) => rel === allowed)) continue;
      const text = readText(file);
      // strip comments / strings is overkill; keep a simple heuristic and trust
      // ESLint to catch the rare false negative once it lands.
      if (FETCH_PATTERN.test(text)) {
        offences.push(rel);
      }
    }
  }
  strictEqual(
    offences.length,
    0,
    `frontend code reached for raw fetch():\n${offences.join('\n')}`,
  );
});
