import { test } from 'node:test';
import { ok, match } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText, tsFilesUnder } from './util.js';

/**
 * 2.5-J2: the demo principal / demo token must NEVER be unconditionally
 * injected by the command-center.
 *
 * The doctrine: in production the frontend is purely representational
 * and MUST NOT produce operational truth (Core Law 1). A demo principal
 * / demo token left ungated means a production build would forward
 * fabricated identity to the backend on every request — which the
 * backend's trusted-ingress middleware correctly rejects, but which
 * the frontend should never have produced in the first place.
 *
 * This test enforces:
 *
 *   1. Only `apps/command-center/src/app/providers.tsx` may reference
 *      the literal `principal-demo` and `demo-token`.
 *   2. In that one allowed file, every reference must appear AFTER a
 *      `USE_MOCK_API` guard — i.e. the literal must not appear before
 *      the dev-flag definition (a coarse but reliable structural pin).
 */

const FORBIDDEN_LITERALS = ['principal-demo', 'demo-token'] as const;

const ALLOWED = join(
  ROOT,
  'apps',
  'command-center',
  'src',
  'app',
  'providers.tsx',
);

test('demo principal / token only appear in providers.tsx', () => {
  const root = join(ROOT, 'apps', 'command-center', 'src');
  for (const path of tsFilesUnder(root)) {
    if (path === ALLOWED) continue;
    // Dev-only mocks live under src/mocks/ — exempt by doctrine.
    if (path.includes(`${join('mocks', '/')}`)) continue;
    const text = readText(path);
    for (const literal of FORBIDDEN_LITERALS) {
      ok(
        !text.includes(literal),
        `${path} contains forbidden literal "${literal}"; ` +
          'demo identity must only live in providers.tsx (gated) or ' +
          'src/mocks/* (dev-only).',
      );
    }
  }
});

test('demo principal / token are gated behind USE_MOCK_API in providers.tsx', () => {
  const text = readText(ALLOWED);
  // The flag must be defined.
  match(
    text,
    /const\s+USE_MOCK_API\s*=/,
    'providers.tsx must define USE_MOCK_API to gate the demo identity',
  );
  // Both literals must follow the flag definition (structural pin).
  const flagIndex = text.indexOf('USE_MOCK_API');
  for (const literal of FORBIDDEN_LITERALS) {
    const idx = text.indexOf(literal);
    ok(idx > flagIndex, `${literal} must appear AFTER the USE_MOCK_API flag`);
  }
  // The conditional principal/token MUST gate on USE_MOCK_API. We
  // pin the canonical pattern so a refactor cannot silently drop
  // the gate.
  match(
    text,
    /USE_MOCK_API\s*\?\s*buildDemoPrincipal\(\)\s*:\s*null/,
    'principal injection must gate on USE_MOCK_API',
  );
  match(
    text,
    /USE_MOCK_API\s*\?\s*'demo-token'\s*:\s*null/,
    'token injection must gate on USE_MOCK_API',
  );
});
