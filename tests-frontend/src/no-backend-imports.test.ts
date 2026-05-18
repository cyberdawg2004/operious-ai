import { test } from 'node:test';
import { strictEqual } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText, tsFilesUnder } from './util.js';

/**
 * Frontend MUST NEVER import from `apps/backend`.
 *
 * The backend is the source of operational truth. The frontend talks to it
 * exclusively through HTTP contracts in `@operious/contracts`. A direct
 * import would mean two things share authority — that violates the law.
 */
const SCAN_ROOTS = [
  join(ROOT, 'apps', 'marketing', 'src'),
  join(ROOT, 'apps', 'command-center', 'src'),
  join(ROOT, 'packages'),
];

const FORBIDDEN_PATTERNS = [
  /from\s+['"][^'"]*apps\/backend/,
  /from\s+['"]\.\.\/\.\.\/apps\/backend/,
  /from\s+['"]@apps\/backend/,
];

test('frontend never imports from apps/backend', () => {
  const offences: string[] = [];
  for (const root of SCAN_ROOTS) {
    for (const file of tsFilesUnder(root)) {
      const text = readText(file);
      for (const pattern of FORBIDDEN_PATTERNS) {
        if (pattern.test(text)) {
          offences.push(file);
          break;
        }
      }
    }
  }
  strictEqual(
    offences.length,
    0,
    `frontend imports from backend:\n${offences.join('\n')}`,
  );
});
