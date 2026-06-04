import { test } from 'node:test';
import { ok, strictEqual } from 'node:assert';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT, readText } from './util.js';

/**
 * Phase 2.5d-platform-scaffold invariants: the separate Platform Console app.
 *
 * This spec is app + auth + gate ONLY. The guarantees that matter at CI:
 *   - the new workspace exists and is registered;
 *   - the OWN Auth0 client bakes in the API audience from day one;
 *   - authority mode is verified-bearer (Bearer, never X-Tenant-ID);
 *   - the ENTIRE app gates on platform.tenant.admin (refusal otherwise);
 *   - the lifecycle client methods hit /tenant/lifecycle/tenants.
 */

const PC = join(ROOT, 'apps', 'platform-console', 'frontend');

const ACCESS = pathToFileURL(join(PC, 'lib', 'platform-access.ts')).href;
const API_CLIENT = pathToFileURL(join(PC, 'lib', 'api-client.ts')).href;

type AccessModule = typeof import(
  '../../apps/platform-console/frontend/lib/platform-access.js'
);
type ApiClientModule = typeof import(
  '../../apps/platform-console/frontend/lib/api-client.js'
);

const access = (await import(ACCESS)) as AccessModule;
const apiClient = (await import(API_CLIENT)) as ApiClientModule;

// ─── Workspace registration ───────────────────────────────────────────────

test('platform-console is registered as a workspace', () => {
  const root = readText(join(ROOT, 'package.json'));
  ok(root.includes('"apps/platform-console/frontend"'));
  const pkg = readText(join(PC, 'package.json'));
  ok(pkg.includes('"@operious/platform-console"'));
  ok(pkg.includes('next build --webpack'));
});

// ─── Own Auth0 client: audience baked in ──────────────────────────────────

test('the Platform Console Auth0 client requests the API audience', () => {
  const auth0 = readText(join(PC, 'lib', 'auth0.ts'));
  ok(auth0.includes('audience'));
  ok(auth0.includes('https://api.operious.ai'), 'audience must be baked in from the start');
  ok(auth0.includes('AUTH0_AUDIENCE'));
  // .env.example documents the placeholders for deploy-time configuration.
  const env = readText(join(PC, '.env.example'));
  ok(env.includes('AUTH0_AUDIENCE=https://api.operious.ai'));
  ok(env.includes('APP_BASE_URL=https://platform.operious.com'));
  ok(env.includes('NEXT_PUBLIC_BACKEND_AUTHORITY_MODE=verified-bearer'));
});

test('the access-token route shape matches Command Center (returns accessToken)', () => {
  const route = readText(join(PC, 'app', 'api', 'auth', 'access-token', 'route.ts'));
  ok(route.includes('auth0.getAccessToken'));
  ok(route.includes('accessToken'));
});

// ─── Authority mode: verified-bearer (behavioral) ─────────────────────────

test('authority mode defaults to verified-bearer (fail-closed)', () => {
  delete process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE;
  delete process.env.NEXT_PUBLIC_OPERIOUS_BACKEND_AUTHORITY_MODE;
  strictEqual(apiClient.getBackendAuthorityMode(), 'verified-bearer');
});

test('tenant-header mode must be opted into explicitly', () => {
  process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE = 'tenant-header';
  strictEqual(apiClient.getBackendAuthorityMode(), 'tenant-header');
  delete process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE;
});

test('the lean api client attaches Bearer, never X-Tenant-ID', () => {
  const api = readText(join(PC, 'lib', 'api.ts'));
  ok(api.includes('Authorization'));
  ok(api.includes('Bearer '));
  // The code must never SET a tenant header (a quoted header literal). A prose
  // mention in a comment is fine; an actual `set("X-Tenant-ID", …)` is not.
  strictEqual(api.includes('"X-Tenant-ID"'), false, 'platform surface must not send tenant headers');
});

// ─── The gate (behavioral) ────────────────────────────────────────────────

const verified = (capabilities: string[]) =>
  ({
    principal_id: 'p1',
    tenant_id: null,
    organization_id: null,
    environment_id: null,
    capabilities,
    authority_source: 'verified',
  }) as never;

test('a principal WITHOUT platform.tenant.admin is refused', () => {
  const state = access.resolvePlatformAccess({
    principal: verified(['tenant.config.write']),
    error: null,
    isLoading: false,
  });
  strictEqual(state, 'refused');
});

test('a verified principal WITH platform.tenant.admin is authorized', () => {
  const state = access.resolvePlatformAccess({
    principal: verified(['platform.tenant.admin']),
    error: null,
    isLoading: false,
  });
  strictEqual(state, 'authorized');
  ok(access.hasPlatformAdmin(verified(['platform.tenant.admin'])));
});

test('loading and unauthenticated states never resolve to authorized', () => {
  strictEqual(
    access.resolvePlatformAccess({ principal: null, error: null, isLoading: true }),
    'loading'
  );
  strictEqual(
    access.resolvePlatformAccess({ principal: null, error: 'API request failed (401)', isLoading: false }),
    'unauthenticated'
  );
  // An anonymous/unverified principal is not platform authority.
  strictEqual(
    access.resolvePlatformAccess({
      principal: {
        principal_id: null,
        tenant_id: null,
        organization_id: null,
        environment_id: null,
        capabilities: ['platform.tenant.admin'],
        authority_source: 'anonymous',
      } as never,
      error: null,
      isLoading: false,
    }),
    'unauthenticated'
  );
});

test('the gate component renders a refusal that names the missing capability', () => {
  const src = readText(join(PC, 'components', 'platform-console.tsx'));
  ok(src.includes('resolvePlatformAccess'));
  ok(src.includes('platform.tenant.admin'));
  ok(src.includes('Not authorized'));
  // Platform content (the shell) is rendered only on the authorized branch.
  ok(src.includes('PlatformShell'));
});

test('logout returnTo is absolute and lands on /sign-in', () => {
  const gate = readText(join(PC, 'components', 'platform-console.tsx'));
  const shell = readText(join(PC, 'components', 'platform-shell.tsx'));
  for (const src of [gate, shell]) {
    ok(src.includes('/api/auth/logout-sign-in'));
    strictEqual(
      src.includes('returnTo=/sign-in'),
      false,
      'logout must not pass a relative returnTo to Auth0'
    );
  }
  const route = readText(join(PC, 'app', 'api', 'auth', 'logout-sign-in', 'route.ts'));
  ok(route.includes('process.env.APP_BASE_URL'));
  ok(route.includes('new URL("/api/auth/logout", appBaseUrl)'));
  ok(route.includes('new URL("/sign-in", appBaseUrl).toString()'));
});

// ─── Lifecycle client methods ─────────────────────────────────────────────

test('lifecycle client methods hit /tenant/lifecycle/tenants', () => {
  const api = readText(join(PC, 'lib', 'api.ts'));
  ok(api.includes('export function createTenantLifecycle'));
  ok(api.includes('export function listTenantLifecycle'));
  ok(api.includes('export function readCurrentPrincipal'));
  ok(api.includes('"/tenant/lifecycle/tenants"'));
  ok(api.includes('"/auth/me"'));
  // The landing page proves the read path end to end.
  const tenants = readText(join(PC, 'app', 'tenants', 'page.tsx'));
  ok(tenants.includes('listTenantLifecycle'));
  ok(tenants.includes('PlatformConsole'));
});
