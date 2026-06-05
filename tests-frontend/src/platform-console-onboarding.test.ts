import { test } from 'node:test';
import { ok, strictEqual } from 'node:assert';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT, readText } from './util.js';

/**
 * Phase 2.5d-platform-onboarding · Part 1 invariants: the Platform Console
 * Phase-A surface (create tenant + re-auth handoff).
 *
 * Phase A is platform-only. It must NOT pull in Phase B (config) machinery —
 * the platform token is never tenant-scoped, so tenant-scoped reads would 400.
 * And the status copy must say active/inert, never "provisioning".
 */

const PC = join(ROOT, 'apps', 'platform-console', 'frontend');
const STATUS = pathToFileURL(join(PC, 'lib', 'tenant-status.ts')).href;

type StatusModule = typeof import(
  '../../apps/platform-console/frontend/lib/tenant-status.js'
);

const status = (await import(STATUS)) as StatusModule;

// ─── Status framing: active/inert, never provisioning (behavioral) ─────────

test('a created tenant is framed active + inert, not provisioning', () => {
  const framing = status.describeTenantStatus('active');
  ok(/inert/i.test(framing.label) || /inert/i.test(framing.detail), 'must convey inert');
  ok(/active/i.test(framing.detail), 'must state status is active');
  ok(!/provisioning/i.test(framing.detail), 'must NOT call a created tenant provisioning');
  ok(/fail-closed|no action policy/i.test(framing.detail), 'must explain inert = missing policy');
});

// ─── The Phase-A surface ──────────────────────────────────────────────────

test('the Phase-A surface creates a tenant and renders the re-auth handoff', () => {
  const src = readText(join(PC, 'components', 'tenant-onboarding.tsx'));
  ok(src.includes('createTenantLifecycle'), 'must call the create lifecycle method');
  ok(src.includes('describeTenantStatus'), 'must use the corrected status framing');
  // The re-auth handoff / isolation-boundary copy.
  ok(/tenant-isolation boundary/i.test(src));
  ok(/Command Center/i.test(src), 'must hand off to the Command Center');
  ok(src.includes('tenant.config.approve'), 'must instruct a separate approver (dual control)');
  ok(src.includes('409'), 'must handle already-exists cleanly');
});

test('the Phase-A surface does NOT pull in Phase B config machinery', () => {
  const src = readText(join(PC, 'components', 'tenant-onboarding.tsx'));
  // The platform token can't do tenant-scoped reads — these must be absent.
  for (const banned of [
    'listChannelConfigurations',
    'listConnectorConfigurations',
    'listGovernancePolicies',
    'listConfigChangeRequests',
    'proposeConfigChangeRequest',
    'config-change-payloads',
    'onboarding-state',
  ]) {
    strictEqual(src.includes(banned), false, `Phase A must not reference ${banned}`);
  }
});

test('Platform Console has NOT imported the CC onboarding modules', () => {
  // The pure modules stay in the Command Center; they must not appear here.
  for (const f of ['lib/onboarding-state.ts', 'lib/config-change-payloads.ts']) {
    let exists = true;
    try {
      readText(join(PC, f));
    } catch {
      exists = false;
    }
    strictEqual(exists, false, `${f} must NOT exist in the Platform Console`);
  }
});

// ─── Routing + nav + gate ─────────────────────────────────────────────────

test('the onboarding route is registered, gated, and protected', () => {
  const page = readText(join(PC, 'app', 'onboarding', 'page.tsx'));
  ok(page.includes('PlatformConsole'), 'route must be wrapped in the platform gate');
  ok(page.includes('TenantOnboarding'));

  const shell = readText(join(PC, 'components', 'platform-shell.tsx'));
  ok(shell.includes('/onboarding'), 'nav must link to onboarding');

  const proxy = readText(join(PC, 'proxy.ts'));
  ok(proxy.includes('/onboarding'), 'middleware must protect /onboarding');
});
