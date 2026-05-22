import { test } from 'node:test';
import { strictEqual } from 'node:assert';
import { join, relative } from 'node:path';
import { ROOT, readText, tsFilesUnder } from './util.js';

/**
 * API paths are owned by `@operious/contracts/endpoints`.
 *
 * No file outside `packages/contracts/src/endpoints.ts` may construct a
 * `/api/v1/...` URL string. This guarantees that an endpoint rename is a
 * single-file change, and that consumers cannot drift.
 */
/**
 * Allowed sites:
 *   - the contract authority itself
 *   - the dev-only mock transport that has to bridge contract paths to fixtures.
 *     This is acceptable because the mock is a transitional artifact and
 *     `mocks/fetch.ts` already routes through the imported `ENDPOINT` map.
 *   - the server-only Auth0 proxy route. It reconstructs `${apiBaseUrl}${path}`
 *     where `path` is the already-namespaced subpath captured from
 *     `/api/proxy/[...path]` — this is the legitimate server-side rejoin
 *     of the same `/api/v*` string the SDK already produced via ENDPOINT.
 */
const ALLOWED_PATHS = [
  join('packages', 'contracts', 'src', 'endpoints.ts'),
  join('apps', 'command-center', 'src', 'mocks', 'fetch.ts'),
  join('apps', 'command-center', 'src', 'app', 'api', 'proxy', '[...path]', 'route.ts'),
];

const SCAN_ROOTS = [
  join(ROOT, 'apps', 'marketing', 'src'),
  join(ROOT, 'apps', 'command-center', 'src'),
  join(ROOT, 'packages'),
];

/**
 * Constitutional path-authority invariant (Core Law 1):
 *
 * Any `/api/v<digit>/` substring anywhere in a TypeScript file outside
 * `ALLOWED_PATHS` is an authority leak — the contract authority is the
 * single source of operational URL truth. The earlier regex required a
 * quote/backtick immediately before `/api/v\d+/`, which missed the
 * template-interpolation pattern `` `${baseUrl}/api/v1/...` ``. The
 * regex below scans for the substring anywhere in the file body.
 */
const PATTERN = /\/api\/v\d+\//;

test('inline /api/v* path strings only live in @operious/contracts', () => {
  const offences: string[] = [];
  for (const root of SCAN_ROOTS) {
    for (const file of tsFilesUnder(root)) {
      const rel = relative(ROOT, file);
      if (ALLOWED_PATHS.some((allowed) => rel === allowed)) continue;
      const text = readText(file);
      if (PATTERN.test(text)) {
        offences.push(rel);
      }
    }
  }
  strictEqual(
    offences.length,
    0,
    `inline /api/v* string outside contracts:\n${offences.join('\n')}`,
  );
});
