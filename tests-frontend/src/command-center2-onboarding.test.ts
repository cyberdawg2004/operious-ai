import { test } from 'node:test';
import { ok, strictEqual, deepStrictEqual } from 'node:assert';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT, readText } from './util.js';

/**
 * Phase 2.5d-platform-onboarding · Part 2 invariants: the Command Center
 * onboarding guide is PHASE B ONLY.
 *
 * Tenant creation (Phase A) is a platform operation and lives in the Platform
 * Console — a tenant operator must never see "create tenant" in the tenant
 * surface. The CC state machine therefore exposes only the four Phase B config
 * steps, gated on the session being tenant-scoped. Step state is still derived
 * from real backend data: a step is `complete` only when its change request is
 * APPLIED (reflected in a read).
 */

const CC2 = join(ROOT, 'apps', 'command-center2', 'frontend');

const STATE = pathToFileURL(join(CC2, 'lib', 'onboarding-state.ts')).href;
const PAYLOADS = pathToFileURL(join(CC2, 'lib', 'config-change-payloads.ts')).href;

type StateModule = typeof import(
  '../../apps/command-center2/frontend/lib/onboarding-state.js'
);
type PayloadsModule = typeof import(
  '../../apps/command-center2/frontend/lib/config-change-payloads.js'
);

const sm = (await import(STATE)) as StateModule;
const payloads = (await import(PAYLOADS)) as PayloadsModule;

type AnySnapshot = Parameters<typeof sm.computeOnboardingSteps>[0];
const snapshot = (over: Partial<AnySnapshot>): AnySnapshot => ({
  principal: null,
  channels: [],
  connectors: [],
  policies: [],
  changeRequests: [],
  ...over,
}) as AnySnapshot;

const stateOf = (steps: ReturnType<typeof sm.computeOnboardingSteps>, id: string) =>
  steps.find((step) => step.id === id)?.state;

// ─── Phase A is gone from the Command Center ───────────────────────────────

test('the CC state machine exposes ONLY the four Phase B steps (no create-tenant)', () => {
  const steps = sm.computeOnboardingSteps(
    snapshot({ principal: { tenant_id: 'tenant-2', capabilities: [] } as never })
  );
  const ids = steps.map((step) => step.id).sort();
  deepStrictEqual(ids, [
    'action-policy',
    'channel',
    'connector',
    'connector-credential',
  ]);
  // The platform-only steps must not exist.
  strictEqual(stateOf(steps, 'create-tenant'), undefined);
  strictEqual(stateOf(steps, 'grant-access'), undefined);
});

// ─── Phase B requires a tenant-scoped session ──────────────────────────────

test('an unscoped session blocks every Phase B step', () => {
  const steps = sm.computeOnboardingSteps(
    snapshot({ principal: { tenant_id: null, capabilities: [] } as never })
  );
  for (const id of ['channel', 'connector', 'connector-credential', 'action-policy']) {
    strictEqual(stateOf(steps, id), 'blocked', `${id} must be blocked when unscoped`);
  }
  strictEqual(sm.isTenantScoped({ tenant_id: null } as never), false);
  strictEqual(sm.isTenantScoped({ tenant_id: 'tenant-2' } as never), true);
});

// ─── Phase B: dependency + governed-lifecycle transitions ──────────────────

test('a tenant-scoped session unlocks channel; connector waits on a channel', () => {
  const principal = { tenant_id: 'tenant-2', capabilities: ['tenant.config.write'] } as never;

  const noChannel = sm.computeOnboardingSteps(snapshot({ principal }));
  strictEqual(stateOf(noChannel, 'channel'), 'available');
  strictEqual(stateOf(noChannel, 'connector'), 'blocked');
  strictEqual(stateOf(noChannel, 'connector-credential'), 'blocked');

  const withChannel = sm.computeOnboardingSteps(
    snapshot({
      principal,
      channels: [{ channel_type: 'shopify', credential_rotated_at: null }] as never,
    })
  );
  strictEqual(stateOf(withChannel, 'channel'), 'complete');
  strictEqual(stateOf(withChannel, 'connector'), 'available');
});

test('a proposed change keeps its step in-progress (not complete) until applied', () => {
  const principal = { tenant_id: 'tenant-2', capabilities: [] } as never;

  const proposed = sm.computeOnboardingSteps(
    snapshot({
      principal,
      changeRequests: [
        {
          change_request_id: 'cr-1',
          change_type: 'channel',
          status: 'PROPOSED',
          proposed_payload: { operation: 'configure' },
        },
      ] as never,
    })
  );
  const channel = proposed.find((step) => step.id === 'channel');
  strictEqual(channel?.state, 'in-progress');
  strictEqual(channel?.pendingChange?.status, 'PROPOSED');

  // Once APPLIED it shows up in the channels read and the step is complete.
  const applied = sm.computeOnboardingSteps(
    snapshot({
      principal,
      channels: [{ channel_type: 'shopify', credential_rotated_at: null }] as never,
    })
  );
  strictEqual(stateOf(applied, 'channel'), 'complete');
});

test('tenant is operational only once an active action_tools policy exists', () => {
  const principal = { tenant_id: 'tenant-2', capabilities: [] } as never;

  const inert = snapshot({ principal });
  strictEqual(sm.tenantIsOperational(inert), false);

  const operational = snapshot({
    principal,
    policies: [{ policy_type: 'action_tools', status: 'active' }] as never,
  });
  strictEqual(sm.tenantIsOperational(operational), true);
  strictEqual(
    stateOf(sm.computeOnboardingSteps(operational), 'action-policy'),
    'complete'
  );
});

// ─── Governed channel-create payload (unchanged, stays in the CC) ──────────

test('governed channel-create payload is a channel change request with credentials', () => {
  const { change_type, payload } = payloads.buildChannelChangePayload({
    channelType: 'shopify',
    routingAddress: 'store.myshopify.com',
    credentials: { access_token: 'shpat_x', blank: '' },
    webhookSecret: 'wh',
  });
  strictEqual(change_type, 'channel');
  strictEqual(payload._schema_version, '1');
  strictEqual(payload.operation, 'configure');
  strictEqual(payload.channel_type, 'shopify');
  deepStrictEqual(payload.credentials, { access_token: 'shpat_x' });
  strictEqual(payload.webhook_secret, 'wh');
  strictEqual(payload.status, 'pending_validation');
});

// ─── The wizard: no create-tenant, composes the proven editors ─────────────

test('the CC onboarding wizard offers NO tenant creation', () => {
  const src = readText(join(CC2, 'components', 'onboarding-wizard.tsx'));
  // The platform-only create path must be gone from the tenant surface.
  strictEqual(src.includes('createTenantLifecycle'), false, 'must not create tenants');
  strictEqual(src.includes('Create tenant'), false, 'must not offer a create-tenant button');
});

test('the CC onboarding wizard composes the proven editors, not duplicate config paths', () => {
  const src = readText(join(CC2, 'components', 'onboarding-wizard.tsx'));
  ok(src.includes('computeOnboardingSteps'), 'wizard must drive the state machine');
  ok(src.includes('buildChannelChangePayload'), 'governed channel create');
  ok(src.includes('dashboardRoutes.connectors'));
  ok(src.includes('dashboardRoutes["action-policy"]'));
  ok(src.includes('dashboardRoutes["config-approvals"]'));
});

// ─── Routing + nav (no longer platform-gated — it's a tenant guide now) ────

test('onboarding route is registered and the nav entry is not platform-gated', () => {
  ok(readText(join(CC2, 'lib', 'dashboard-routes.ts')).includes('"/dashboard/onboarding"'));
  ok(readText(join(CC2, 'app', 'dashboard', 'onboarding', 'page.tsx')).length > 0);
  const sidebar = readText(join(CC2, 'components', 'sidebar.tsx'));
  const onboardingLine =
    sidebar.split('\n').find((line) => line.includes('dashboardRoutes.onboarding')) ?? '';
  ok(onboardingLine.length > 0, 'onboarding nav entry must exist');
  strictEqual(
    onboardingLine.includes('platform.tenant.admin'),
    false,
    'CC onboarding is a tenant-config guide — it must not require platform.tenant.admin'
  );
});

// ─── Status copy: created tenants are active-but-inert, not provisioning ───

test('CC status copy no longer claims a created tenant is provisioning', () => {
  const api = readText(join(CC2, 'lib', 'api.ts'));
  // The TenantLifecycleRecord doc must not assert tenants are created provisioning.
  ok(/creates a tenant with status `active`/i.test(api) || /status `active`/i.test(api));
  ok(!/is INERT — it is\s*\n?\s*\*?`?provisioning`?/i.test(api), 'must not call new tenants provisioning');
});
