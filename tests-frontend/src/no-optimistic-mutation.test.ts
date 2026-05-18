import { test } from 'node:test';
import { strictEqual } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText, tsFilesUnder } from './util.js';

/**
 * Frontend hardening: no optimistic operational mutation.
 *
 * Operious forbids the "optimistic UI" pattern. Every mutation must wait for
 * a backend confirmation envelope; UI cannot pretend an operation succeeded
 * while the backend is still deliberating.
 *
 * Concretely, in our stack that means:
 *   - TanStack Query mutation hooks must NOT use `onMutate` for cache writes
 *   - Mutation hooks must explicitly set `retry: false`
 *   - We never call `setQueryData(...)` ahead of a backend response
 */
const SCAN_ROOTS = [
  join(ROOT, 'apps', 'marketing', 'src'),
  join(ROOT, 'apps', 'command-center', 'src'),
  join(ROOT, 'packages'),
];

const FORBIDDEN_TOKENS = [
  /onMutate\s*:/,
  /\bsetQueryData\s*\(/,
  /optimisticUpdate/i,
];

test('no optimistic mutation tokens leak into the frontend', () => {
  const offences: string[] = [];
  for (const root of SCAN_ROOTS) {
    for (const file of tsFilesUnder(root)) {
      const text = readText(file);
      for (const pattern of FORBIDDEN_TOKENS) {
        if (pattern.test(text)) {
          offences.push(`${file}: ${pattern.toString()}`);
        }
      }
    }
  }
  strictEqual(
    offences.length,
    0,
    `optimistic mutation tokens detected:\n${offences.join('\n')}`,
  );
});

test('every SDK mutation hook explicitly sets retry: false', () => {
  const file = join(ROOT, 'packages', 'sdk', 'src', 'mutations.ts');
  const text = readText(file);
  const useMutationCalls = text.match(/useMutation</g) ?? [];
  const retryFalse = text.match(/retry:\s*false/g) ?? [];
  strictEqual(
    retryFalse.length >= useMutationCalls.length,
    true,
    `each useMutation call in ${file} must set retry: false (saw ${useMutationCalls.length} hooks but only ${retryFalse.length} retry guards)`,
  );
});
