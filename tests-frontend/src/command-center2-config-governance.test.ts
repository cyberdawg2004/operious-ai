import { test } from 'node:test';
import { ok, strictEqual, deepStrictEqual } from 'node:assert';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT, readText } from './util.js';

/**
 * Phase 2.5b-ui invariants: connector-config + action-policy editors and the
 * config-change approval surface that drive the governed change-request ledger.
 *
 * Two things are guarded hardest here (Step 0 hard constraints):
 *   A. credentials never travel the connector config path — and a credential
 *      value entered anywhere is never rendered back.
 *   D. edits are governed (proposed → approved → applied), never direct writes.
 */

const CC2 = join(ROOT, 'apps', 'command-center2', 'frontend');
const PAYLOADS = pathToFileURL(
  join(CC2, 'lib', 'config-change-payloads.ts'),
).href;

type PayloadsModule = typeof import(
  '../../apps/command-center2/frontend/lib/config-change-payloads.js'
);

const payloads = (await import(PAYLOADS)) as PayloadsModule;

// ─── Constraint A: connector payload is credential-free ───────────────────

test('connector change payload is credential-free and well-formed', () => {
  const { change_type, payload } = payloads.buildConnectorChangePayload({
    connector_type: 'shopify',
    tool_name: 'refund.request',
    http_method: 'post',
    endpoint_template: 'https://api.example.com/refund',
    endpoint_host: 'api.example.com',
    field_mappings: { order_id: 'orderId' },
    idempotency_header_name: 'Idempotency-Key',
    response_parse: { ok: 'status' },
    success_status_codes: [200, 201],
  });
  strictEqual(change_type, 'connector');
  strictEqual(payload._schema_version, '1');
  strictEqual(payload.operation, 'configure');
  strictEqual(payload.http_method, 'POST');
  strictEqual(payloads.payloadContainsCredentialKeys(payload), false);
});

test('connector builder strips forbidden credential keys at any depth', () => {
  const dirty = {
    connector_type: 'shopify',
    tool_name: 'refund.request',
    http_method: 'POST',
    endpoint_template: 'https://api.example.com/refund',
    endpoint_host: 'api.example.com',
    // A UI mistake nests a secret inside a config field — it must be stripped.
    field_mappings: { access_token: 'leak', order_id: 'orderId' },
    idempotency_header_name: 'Idempotency-Key',
    response_parse: {},
    success_status_codes: [200],
    // and a top-level credential leak:
    credentials: { api_key: 'secret' },
    webhook_secret: 'shhh',
  } as unknown as Parameters<typeof payloads.buildConnectorChangePayload>[0];

  const { payload } = payloads.buildConnectorChangePayload(dirty);
  strictEqual(payloads.payloadContainsCredentialKeys(payload), false);
  const mappings = payload.field_mappings as Record<string, unknown>;
  strictEqual('access_token' in mappings, false);
  strictEqual(mappings.order_id, 'orderId');
});

test('forbidden credential key set mirrors the backend validator', () => {
  const keys = [...payloads.CONNECTOR_FORBIDDEN_CREDENTIAL_KEYS].sort();
  deepStrictEqual(keys, [
    'access_token',
    'api_key',
    'auth_header',
    'bearer_token',
    'credential',
    'credentials',
    'credentials_enc',
    'webhook_secret',
  ]);
});

// ─── Constraint A (step ii): channel credential path is write-only ─────────

test('channel credential payload omits blank fields (blank = keep current)', () => {
  const { change_type, payload } = payloads.buildChannelCredentialChangePayload({
    configId: 'cfg-1',
    credentials: { access_token: '', smtp_password: '   ' },
    webhookSecret: '',
  });
  strictEqual(change_type, 'channel');
  strictEqual(payload.operation, 'update');
  strictEqual(payload.config_id, 'cfg-1');
  // Nothing was typed — no credential keys are sent at all.
  strictEqual('credentials' in payload, false);
  strictEqual('webhook_secret' in payload, false);
});

test('channel credential payload includes only typed credential values', () => {
  const { payload } = payloads.buildChannelCredentialChangePayload({
    configId: 'cfg-1',
    credentials: { access_token: 'new-token', smtp_password: '' },
    webhookSecret: 'wh',
  });
  deepStrictEqual(payload.credentials, { access_token: 'new-token' });
  strictEqual(payload.webhook_secret, 'wh');
});

test('whatsapp self-service channel payload keeps only typed secrets', () => {
  const { change_type, payload } = payloads.buildWhatsAppSelfServiceChannelChangePayload({
    waba_id: 'waba-1',
    phone_number_id: 'phone-1',
    graph_api_version: 'v25.0',
    access_token: 'token',
    webhook_verify_token: '',
  });
  strictEqual(change_type, 'channel');
  strictEqual(payload.channel_type, 'whatsapp');
  strictEqual(payload.routing_address, 'phone-1');
  strictEqual(payload.status, 'pending_validation');
  deepStrictEqual(payload.self_service_config, {
    setup: 'manual_token',
    waba_id: 'waba-1',
    phone_number_id: 'phone-1',
    graph_api_version: 'v25.0',
  });
  deepStrictEqual(payload.credentials, {
    access_token: 'token',
    provider: 'meta_whatsapp_manual',
    phone_number_id: 'phone-1',
    graph_api_version: 'v25.0',
  });
});

test('ses self-service channel payload supports managed and byo access-key modes', () => {
  const managed = payloads.buildSesSelfServiceChannelChangePayload({
    mode: 'managed',
    region: 'us-east-1',
    source_domain: 'example.com',
    inbound_address: 'support@example.com',
  }).payload;
  strictEqual(managed.channel_type, 'email');
  strictEqual(managed.routing_address, 'support@example.com');
  strictEqual(managed.status, 'pending_validation');
  deepStrictEqual(managed.self_service_config, {
    mode: 'managed',
    region: 'us-east-1',
    source_domain: 'example.com',
    inbound_address: 'support@example.com',
  });

  const byo = payloads.buildSesSelfServiceChannelChangePayload({
    mode: 'byo_access_key',
    region: 'us-east-1',
    source_email: 'support@example.com',
    access_key_id: 'AKIA',
    secret_access_key: '',
  }).payload;
  deepStrictEqual(byo.credentials, {
    access_key_id: 'AKIA',
    mode: 'byo_access_key',
    region: 'us-east-1',
    source_email_address: 'support@example.com',
  });
});

// ─── action_tools policy mapping ──────────────────────────────────────────

test('action policy parameters carry all four required tool rules', () => {
  const params = payloads.buildActionPolicyParameters({
    warrantyConfidenceGte: 0.8,
    warrantyIssueCategories: ['defect'],
    warrantyElse: 'require_approval',
    replacementAlways: 'allow',
    refundAmountCentsLte: 5000,
    refundConfidenceGte: 0.9,
    refundElse: 'deny',
    warehouseAllowSeverities: ['low'],
    warehouseRequireApprovalSeverities: ['high'],
  });
  const tools = params.tools as Record<string, unknown>;
  for (const rule of [
    'warranty.claim',
    'replacement.order',
    'refund.request',
    'warehouse.repair.report',
  ]) {
    ok(rule in tools, `missing tool rule ${rule}`);
  }
});

test('action policy change payload includes policy_id only on update', () => {
  const created = payloads.buildActionPolicyChangePayload({
    effectiveFrom: '2026-06-04T00:00:00.000Z',
    warrantyConfidenceGte: 0.8,
    warrantyIssueCategories: ['defect'],
    warrantyElse: 'deny',
    replacementAlways: 'allow',
    refundAmountCentsLte: 5000,
    refundConfidenceGte: null,
    refundElse: 'deny',
    warehouseAllowSeverities: ['low'],
    warehouseRequireApprovalSeverities: ['high'],
  });
  strictEqual(created.change_type, 'policy');
  strictEqual(created.payload.policy_type, 'action_tools');
  strictEqual('policy_id' in created.payload, false);

  const updated = payloads.buildActionPolicyChangePayload({
    policyId: 'pol-1',
    warrantyConfidenceGte: 0.8,
    warrantyIssueCategories: ['defect'],
    warrantyElse: 'deny',
    replacementAlways: 'allow',
    refundAmountCentsLte: 5000,
    refundElse: 'deny',
    warehouseAllowSeverities: ['low'],
    warehouseRequireApprovalSeverities: ['high'],
  });
  strictEqual(updated.payload.operation, 'update');
  strictEqual(updated.payload.policy_id, 'pol-1');
});

// ─── Constraint C: client-side change_type filter ─────────────────────────

test('client-side filter keeps connector, action_tools policy, and knowledge upload changes', () => {
  const items = [
    { change_type: 'connector' as const, proposed_payload: {} },
    {
      change_type: 'policy' as const,
      proposed_payload: { policy_type: 'action_tools' },
    },
    {
      change_type: 'policy' as const,
      proposed_payload: { policy_type: 'something_else' },
    },
    { change_type: 'channel' as const, proposed_payload: {} },
    { change_type: 'knowledge' as const, proposed_payload: {} },
  ];
  const kept = payloads.filterConfigChangeRequests(items);
  strictEqual(kept.length, 3);
  strictEqual(payloads.classifyConfigChange(items[0]), 'connector');
  strictEqual(payloads.classifyConfigChange(items[1]), 'action_policy');
  strictEqual(payloads.classifyConfigChange(items[2]), null);
  strictEqual(payloads.classifyConfigChange(items[3]), null);
  strictEqual(payloads.classifyConfigChange(items[4]), 'knowledge');
});

// ─── API client surface ───────────────────────────────────────────────────

test('api client exposes the connector reads + change-request ledger', () => {
  const api = readText(join(CC2, 'lib', 'api.ts'));
  for (const fn of [
    'export function listConnectorConfigurations',
    'export function listConnectorConfigurationHistory',
    'export function proposeConfigChangeRequest',
    'export function listConfigChangeRequests',
    'export function approveConfigChangeRequest',
    'export function rejectConfigChangeRequest',
    'export function applyConfigChangeRequest',
    'export function revokeConfigChangeRequest',
  ]) {
    ok(api.includes(fn), `api.ts missing ${fn}`);
  }
  // Endpoints hit the proven 2.5a/2.5b-api routes.
  ok(api.includes('"/tenant/connectors"'));
  ok(api.includes('"/tenant/config/change-requests"'));
  ok(api.includes('/approve'));
  ok(api.includes('/reject'));
  ok(api.includes('/apply'));
  ok(api.includes('/revoke'));
});

// ─── Routing registration ─────────────────────────────────────────────────

test('three config-governance routes are registered', () => {
  const routes = readText(join(CC2, 'lib', 'dashboard-routes.ts'));
  ok(routes.includes('"/dashboard/connectors"'));
  ok(routes.includes('"/dashboard/action-policy"'));
  ok(routes.includes('"/dashboard/config-approvals"'));

  for (const page of [
    join('app', 'dashboard', 'connectors', 'page.tsx'),
    join('app', 'dashboard', 'action-policy', 'page.tsx'),
    join('app', 'dashboard', 'config-approvals', 'page.tsx'),
  ]) {
    ok(readText(join(CC2, page)).length > 0, `missing page ${page}`);
  }

  const sidebar = readText(join(CC2, 'components', 'sidebar.tsx'));
  ok(sidebar.includes('dashboardRoutes.connectors'));
  ok(sidebar.includes('dashboardRoutes["action-policy"]'));
  ok(sidebar.includes('dashboardRoutes["config-approvals"]'));
});

// ─── Constraint A: credential never rendered back in the editors ───────────

test('connector editor drives the credential-free builder and a separate credential step', () => {
  const src = readText(join(CC2, 'components', 'connector-config-views.tsx'));
  ok(src.includes('buildConnectorChangePayload'), 'connector form must use the safe builder');
  ok(
    src.includes('buildChannelCredentialChangePayload'),
    'credential rotation must use the channel credential path',
  );
  // Write-only credential UX, mirrored from the channel form.
  ok(src.includes('Leave blank to keep current value'));
  // The connector config form must not contain credential input field keys.
  ok(!src.includes('credentials_enc'));
});

test('channels view does not expose unsafe direct verify', () => {
  const src = readText(join(CC2, 'components', 'integration-views.tsx'));
  ok(!src.includes('verifyChannelConfiguration'));
  ok(!src.includes('/verify'));
  ok(src.includes('createWhatsAppSelfServiceChannel'));
  ok(src.includes('createSesSelfServiceChannel'));
});

// ─── Constraint D: governed lifecycle is shown, never a direct write ───────

test('config-change approval surface mirrors the inbox over the ledger', () => {
  const src = readText(join(CC2, 'components', 'config-change-approvals.tsx'));
  ok(src.includes('listConfigChangeRequests'));
  ok(src.includes('approveConfigChangeRequest'));
  ok(src.includes('rejectConfigChangeRequest'));
  // Client-side change_type filtering (constraint C).
  ok(src.includes('filterConfigChangeRequests') || src.includes('classifyConfigChange'));
  // Governed lifecycle is surfaced to the operator (constraint D).
  for (const phase of ['PROPOSED', 'APPROVED', 'APPLIED']) {
    ok(src.includes(phase), `approval surface should surface ${phase} status`);
  }
});
