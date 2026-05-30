import { test } from 'node:test';
import { strictEqual } from 'node:assert';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// Resolved without `import.meta.dirname` so the suite runs on Node 18+.
const HERE = dirname(fileURLToPath(import.meta.url));
const API_CLIENT = join(
  HERE,
  '..',
  '..',
  'apps',
  'command-center2',
  'frontend',
  'lib',
  'api-client.ts',
);

// Import the real module so we test behaviour, not source text.
const { getBackendAuthorityMode } = (await import(API_CLIENT)) as {
  getBackendAuthorityMode: () => 'tenant-header' | 'verified-bearer';
};

test('authority mode defaults to verified-bearer (fail-closed, S-01)', () => {
  delete process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE;
  delete process.env.NEXT_PUBLIC_OPERIOUS_BACKEND_AUTHORITY_MODE;
  strictEqual(getBackendAuthorityMode(), 'verified-bearer');
});

test('verified-bearer can be requested explicitly', () => {
  process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE = 'auth0';
  strictEqual(getBackendAuthorityMode(), 'verified-bearer');
  delete process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE;
});

test('tenant-header mode must be opted into explicitly', () => {
  process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE = 'tenant-header';
  strictEqual(getBackendAuthorityMode(), 'tenant-header');
  delete process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE;
});
