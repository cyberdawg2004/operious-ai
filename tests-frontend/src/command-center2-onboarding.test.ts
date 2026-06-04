import { test } from 'node:test';
import { ok, strictEqual, deepStrictEqual } from 'node:assert';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT, readText } from './util.js';

/**
 * Phase 2.5d invariants: the governed onboarding orchestration surface.
 *
 * The sophistication being guarded is the STATE MACHINE — step state is
 * derived from real backend data, a step is `complete` only when its change
 * request is APPLIED (reflected in a read), and Phase B is gated on the
 * acting token being scoped to the target tenant (the re-auth boundary).
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

// Minimal snapshot factory — only the fields the state machine reads.
type AnySnapshot = Parameters<typeof sm.computeOnboardingSteps>[0];
const emptySnapshot = (over: Partial<AnySnapshot>): AnySnapshot => ({
  targetTenantId: 'tenant-2',
  principal: null,
  tenants: [],
  channels: [],
  connectors: [],
  policies: [],
  changeRequests: [],
  ...over,
}) as AnySnapshot;

const stateOf = (steps: ReturnType<typeof sm.computeOnboardingSteps>, id: string) =>
  steps.find((step) => step.id === id)?.state;

// ─── Phase A: platform gate + inert create ────────────────────────────────

test('create-tenant is blocked without platform.tenant.admin', () => {
  const steps = sm.computeOnboardingSteps(
    emptySnapshot({ principal: { capabilities: [] } as never })
  );
  strictEqual(stateOf(steps, 'create-tenant'), 'blocked');
});

test('create-tenant is available for a platform admin, complete once the tenant exists', () => {
  const principal = { capabilities: ['platform.tenant.admin'] } as never;
  const available = sm.computeOnboardingSteps(emptySnapshot({ principal }));
  strictEqual(stateOf(available, 'create-tenant'), 'available');

  const created = sm.computeOnboardingSteps(
    emptySnapshot({
      principal,
      tenants: [{ tenant_id: 'tenant-2', status: 'provisioning', created_at: 'x' }] as never,
    })
  );
  strictEqual(stateOf(created, 'create-tenant'), 'complete');
});

// ─── Phase A → B: the re-auth boundary ────────────────────────────────────

test('grant-access (re-auth boundary) gates Phase B until the token is scoped to the target tenant', () => {
  const principal = {
    capabilities: ['platform.tenant.admin'],
    tenant_id: 'tenant-1', // still scoped to the OLD tenant
  } as never;
  const tenants = [{ tenant_id: 'tenant-2', status: 'provisioning', created_at: 'x' }] as never;

  const beforeReauth = sm.computeOnboardingSteps(emptySnapshot({ principal, tenants }));
  strictEqual(stateOf(beforeReauth, 'grant-access'), 'available');
  // Every Phase B step is blocked while the token is not scoped to tenant-2.
  strictEqual(stateOf(beforeReauth, 'channel'), 'blocked');
  strictEqual(stateOf(beforeReauth, 'connector'), 'blocked');
  strictEqual(stateOf(beforeReauth, 'connector-credential'), 'blocked');
  strictEqual(stateOf(beforeReauth, 'action-policy'), 'blocked');
  strictEqual(sm.tokenScopedToTarget(emptySnapshot({ principal, tenants })), false);

  const scopedPrincipal = {
    capabilities: ['tenant.config.write'],
    tenant_id: 'tenant-2',
  } as never;
  const afterReauth = sm.computeOnboardingSteps(
    emptySnapshot({ principal: scopedPrincipal, tenants })
  );
  strictEqual(stateOf(afterReauth, 'grant-access'), 'complete');
  strictEqual(stateOf(afterReauth, 'channel'), 'available');
});

// ─── Phase B: dependency + governed-lifecycle transitions ─────────────────

test('connector and credential steps are blocked until a matching channel exists', () => {
  const principal = { capabilities: [], tenant_id: 'tenant-2' } as never;
  const tenants = [{ tenant_id: 'tenant-2', status: 'provisioning', created_at: 'x' }] as never;

  const noChannel = sm.computeOnboardingSteps(emptySnapshot({ principal, tenants }));
  strictEqual(stateOf(noChannel, 'channel'), 'available');
  strictEqual(stateOf(noChannel, 'connector'), 'blocked');
  strictEqual(stateOf(noChannel, 'connector-credential'), 'blocked');

  const withChannel = sm.computeOnboardingSteps(
    emptySnapshot({
      principal,
      tenants,
      channels: [{ channel_type: 'shopify', credential_rotated_at: null }] as never,
    })
  );
  strictEqual(stateOf(withChannel, 'channel'), 'complete');
  strictEqual(stateOf(withChannel, 'connector'), 'available');
});

test('a proposed change keeps its step in-progress (not complete) until applied', () => {
  const principal = { capabilities: [], tenant_id: 'tenant-2' } as never;
  const tenants = [{ tenant_id: 'tenant-2', status: 'provisioning', created_at: 'x' }] as never;

  const proposed = sm.computeOnboardingSteps(
    emptySnapshot({
      principal,
      tenants,
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

  // Once APPLIED, it shows up in the channels read and the step is complete.
  const applied = sm.computeOnboardingSteps(
    emptySnapshot({
      principal,
      tenants,
      channels: [{ channel_type: 'shopify', credential_rotated_at: null }] as never,
    })
  );
  strictEqual(stateOf(applied, 'channel'), 'complete');
});

test('tenant is operational only once an active action_tools policy exists', () => {
  const principal = { capabilities: [], tenant_id: 'tenant-2' } as never;
  const tenants = [{ tenant_id: 'tenant-2', status: 'provisioning', created_at: 'x' }] as never;

  const inert = emptySnapshot({ principal, tenants });
  strictEqual(sm.tenantIsOperational(inert), false);

  const operational = emptySnapshot({
    principal,
    tenants,
    policies: [{ policy_type: 'action_tools', status: 'active' }] as never,
  });
  strictEqual(sm.tenantIsOperational(operational), true);
  strictEqual(
    stateOf(sm.computeOnboardingSteps(operational), 'action-policy'),
    'complete'
  );
});

// ─── Net-new governed channel-create payload ──────────────────────────────

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
  // Blank credential values are dropped; provided ones survive.
  deepStrictEqual(payload.credentials, { access_token: 'shpat_x' });
  strictEqual(payload.webhook_secret, 'wh');
});

// ─── API surface + routing registration ───────────────────────────────────

test('api client exposes the tenant lifecycle reads/writes', () => {
  const api = readText(join(CC2, 'lib', 'api.ts'));
  ok(api.includes('export function createTenantLifecycle'));
  ok(api.includes('export function listTenantLifecycle'));
  ok(api.includes('"/tenant/lifecycle/tenants"'));
});

test('onboarding route is registered and capability-gated in the nav', () => {
  ok(readText(join(CC2, 'lib', 'dashboard-routes.ts')).includes('"/dashboard/onboarding"'));
  ok(readText(join(CC2, 'app', 'dashboard', 'onboarding', 'page.tsx')).length > 0);
  const sidebar = readText(join(CC2, 'components', 'sidebar.tsx'));
  // The wizard entry is surfaced only to platform.tenant.admin principals.
  ok(sidebar.includes('platform.tenant.admin'));
});

test('onboarding wizard composes the proven editors, not duplicate config paths', () => {
  const src = readText(join(CC2, 'components', 'onboarding-wizard.tsx'));
  ok(src.includes('computeOnboardingSteps'), 'wizard must drive the state machine');
  ok(src.includes('buildChannelChangePayload'), 'governed channel create');
  // Reuse the 2.5b editors for connector/policy rather than re-implementing.
  ok(src.includes('dashboardRoutes.connectors'));
  ok(src.includes('dashboardRoutes["action-policy"]'));
  ok(src.includes('dashboardRoutes["config-approvals"]'));
});
