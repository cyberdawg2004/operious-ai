"use client";

import {
  useCallback,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  CheckCircle2,
  CircleAlert,
  KeyRound,
  Link2,
  PlugZap,
  RefreshCw,
  Shield,
  Sliders,
  TestTubeDiagonal,
  X,
} from "lucide-react";
import {
  ApiError,
  formatApiError,
  getConfiguredTenantId,
  listChannelConfigurations,
  listConfigChangeRequests,
  listConnectorConfigurations,
  listConnectorConfigurationHistory,
  listGovernancePolicies,
  proposeConnectorCredentials,
  proposeConfigChangeRequest,
  testConnectorConfiguration,
  type TenantChannelConfiguration,
  type TenantConfigChangeRequest,
  type TenantConnectorConfiguration,
  type TenantConnectorTestResponse,
  type TenantGovernancePolicy,
  type TenantOmsCredentialRequest,
} from "@/lib/api";
import {
  ACTION_TOOLS_POLICY_TYPE,
  CONNECTOR_STATUS_OPTIONS,
  CONNECTOR_TYPE_OPTIONS,
  HTTP_METHOD_OPTIONS,
  POLICY_DECISION_VALUES,
  buildActionPolicyChangePayload,
  buildConnectorChangePayload,
  classifyConfigChange,
  type PolicyDecision,
} from "@/lib/config-change-payloads";
import { useAuthSession } from "@/lib/use-auth-session";
import { useApiResource } from "@/lib/use-api-resource";
import { ConfigChangeApprovals } from "@/components/config-change-approvals";
import { McpConnectorView } from "@/components/mcp-connector-views";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { TechnicalDetails } from "@/components/technical-details";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  CodeAsReadableText,
  DownloadableLog,
} from "@/components/ui/readable-data";
import { StatusBadge } from "@/components/ui/status-badge";

const TENANT_CONNECTOR_WRITE_CAPABILITY = "tenant.connector.write";
const RESOLUTION_TAXONOMY_POLICY_TYPE = "resolution_taxonomy";

const CONNECTOR_TOOLS = [
  {
    toolName: "refund.request",
    label: "Refund Request",
    summary: "Execute outbound refund remedies against the tenant's endpoint.",
    defaultConnectorType: "oms",
  },
  {
    toolName: "warranty.claim",
    label: "Warranty Claim",
    summary: "Create tenant-configured warranty claims through the generic connector.",
    defaultConnectorType: "oms",
  },
  {
    toolName: "replacement.order",
    label: "Replacement Order",
    summary: "Submit replacement orders through the tenant's configured connector.",
    defaultConnectorType: "oms",
  },
  {
    toolName: "repair.dispatch",
    label: "Repair Dispatch",
    summary: "Dispatch repair work to the tenant's selected repair provider endpoint.",
    defaultConnectorType: "zendesk",
  },
] as const;

const OMS_AUTH_TYPES = ["bearer", "api_key", "basic"] as const;
const OMS_CREDENTIAL_TOOL_NAME = "refund.request";

type ConnectorToolDefinition = (typeof CONNECTOR_TOOLS)[number];

type ConnectorModal =
  | { type: "none" }
  | {
      type: "configure";
      tool: ConnectorToolDefinition | CustomConnectorTool;
      connector: TenantConnectorConfiguration | null;
    }
  | { type: "credential" }
  | { type: "add_custom" }
  | {
      type: "custom_credential";
      connectorId: string;
      toolName: string;
      label: string;
    };

type CustomConnectorTool = {
  toolName: string;
  label: string;
  summary: string;
  defaultConnectorType: string;
  isCustom: true;
};

type KeyValueRow = {
  id: string;
  key: string;
  value: string;
};

type ConnectorDashboardData = {
  channels: TenantChannelConfiguration[];
  policies: TenantGovernancePolicy[];
  pendingRequests: TenantConfigChangeRequest[];
  connectorHistory: Record<string, TenantConnectorConfiguration[]>;
  customToolNames: string[];
};

type ConnectorCardStatus = "active" | "inactive" | "pending_approval";

type GateState = {
  connectorConfigured: boolean;
  actionPolicyActive: boolean;
  taxonomyRequiresExecution: boolean;
  armed: boolean;
  policyHint: string;
  taxonomyHint: string;
};

type ConnectorCardView = {
  tool: ConnectorToolDefinition | CustomConnectorTool;
  connector: TenantConnectorConfiguration | null;
  pendingRequestCount: number;
  pendingProposal: Record<string, unknown> | null;
  status: ConnectorCardStatus;
  endpointPreview: string;
  gateState: GateState;
};

type TestState = {
  busy: boolean;
  data: TenantConnectorTestResponse | null;
  error: string | null;
};

type ExistingActionPolicy = {
  warrantyConfidenceGte?: number;
  warrantyIssueCategories?: string[];
  warrantyElse?: PolicyDecision;
  replacementAlways?: PolicyDecision;
  refundAmountCentsLte?: number;
  refundConfidenceGte?: number | null;
  refundElse?: PolicyDecision;
  warehouseAllowSeverities?: string[];
  warehouseRequireApprovalSeverities?: string[];
};

async function fetchConnectorHistory(
  toolName: string
): Promise<TenantConnectorConfiguration[]> {
  try {
    const page = await listConnectorConfigurationHistory(toolName, { limit: 25, offset: 0 });
    return page.items;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return [];
    throw err;
  }
}

export function ConnectorConfigView() {
  const { principal } = useAuthSession();
  const [modal, setModal] = useState<ConnectorModal>({ type: "none" });
  const [notice, setNotice] = useState<string | null>(null);
  const [testStates, setTestStates] = useState<Record<string, TestState>>({});

  const tenantId = principal?.tenant_id ?? getConfiguredTenantId();
  const canWrite = principal?.capabilities.includes(TENANT_CONNECTOR_WRITE_CAPABILITY) ?? false;

  const load = useCallback(async (): Promise<ConnectorDashboardData> => {
    const builtinToolNames: string[] = CONNECTOR_TOOLS.map((t) => t.toolName);

    const [channels, policies, proposed, approved, allConfigs, histories] =
      await Promise.all([
        listChannelConfigurations(),
        listGovernancePolicies(),
        listConfigChangeRequests({ status: "PROPOSED", limit: 100, offset: 0 }),
        listConfigChangeRequests({ status: "APPROVED", limit: 100, offset: 0 }),
        listConnectorConfigurations({ limit: 100, offset: 0 }),
        Promise.all(
          CONNECTOR_TOOLS.map(
            async (tool): Promise<[string, TenantConnectorConfiguration[]]> => [
              tool.toolName,
              await fetchConnectorHistory(tool.toolName),
            ]
          )
        ),
      ]);

    // Discover custom connector tool names: any active config not in the built-in set.
    const customToolNames = allConfigs.items
      .map((c) => c.tool_name)
      .filter((name) => !builtinToolNames.includes(name));

    // Fetch history for custom connectors too.
    const customHistories = await Promise.all(
      customToolNames.map(
        async (toolName): Promise<[string, TenantConnectorConfiguration[]]> => [
          toolName,
          await fetchConnectorHistory(toolName),
        ]
      )
    );

    return {
      channels: channels.items,
      policies: policies.items,
      pendingRequests: [...proposed.items, ...approved.items].filter(
        (request) => classifyConfigChange(request) === "connector"
      ),
      connectorHistory: Object.fromEntries([...histories, ...customHistories]),
      customToolNames,
    };
  }, []);

  const { data, error, isLoading, reload } = useApiResource(load);

  const cards = useMemo(() => {
    const policies = data?.policies ?? [];
    const pendingRequests = data?.pendingRequests ?? [];
    const history = data?.connectorHistory ?? {};
    const customToolNames = data?.customToolNames ?? [];

    const builtinCards = CONNECTOR_TOOLS.map((tool) =>
      buildConnectorCardView({
        tool,
        history: history[tool.toolName] ?? [],
        pendingRequests,
        policies,
      })
    );

    const customCards = customToolNames.map((toolName) => {
      const customTool: CustomConnectorTool = {
        toolName,
        label: toolName,
        summary: "Custom connector configured by this tenant.",
        defaultConnectorType: toolName.includes(".")
          ? toolName.split(".")[0]!
          : toolName,
        isCustom: true,
      };
      return buildConnectorCardView({
        tool: customTool,
        history: history[toolName] ?? [],
        pendingRequests,
        policies,
      });
    });

    return [...builtinCards, ...customCards];
  }, [data]);

  const omsCredentialState = useMemo(
    () => selectOmsCredentialState(data?.channels ?? []),
    [data]
  );
  const omsCredentialPendingCount = useMemo(
    () =>
      (data?.pendingRequests ?? []).filter(
        (request) => request.change_type === "credential_update"
      ).length,
    [data]
  );

  const runTest = async (toolName: string) => {
    if (!tenantId) {
      setTestStates((current) => ({
        ...current,
        [toolName]: {
          busy: false,
          data: null,
          error: "Tenant scope is missing, so the safe connector test cannot run.",
        },
      }));
      return;
    }

    setTestStates((current) => ({
      ...current,
      [toolName]: { busy: true, data: null, error: null },
    }));
    try {
      const result = await testConnectorConfiguration(tenantId, toolName);
      setTestStates((current) => ({
        ...current,
        [toolName]: { busy: false, data: result, error: null },
      }));
    } catch (caught: unknown) {
      setTestStates((current) => ({
        ...current,
        [toolName]: {
          busy: false,
          data: null,
          error: formatApiError(caught),
        },
      }));
    }
  };

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-8">
      <Header eyebrow="BOUNDARY · CONNECTORS" title="Connector Command Center" />

      <div className="mb-6 grid grid-cols-1 gap-3 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Execution Safety</CardTitle>
              <CardDescription>
                Connector writes remain dual-controlled. A connector executes only
                when configuration, action-policy authority, and taxonomy execution
                intent are all present.
              </CardDescription>
            </div>
            <StatusBadge
              label={canWrite ? "Write enabled" : "Read only"}
              tone={canWrite ? "success" : "warning"}
              icon={canWrite ? Shield : CircleAlert}
            />
          </CardHeader>
          <div className="grid gap-3 text-[13px] text-ink-secondary md:grid-cols-3">
            <GateExplainer
              title="Gate 1"
              body="Active connector config exists for the action tool."
            />
            <GateExplainer
              title="Gate 2"
              body="An active action_tools policy rule exists for that tool."
            />
            <GateExplainer
              title="Gate 3"
              body="The active resolution taxonomy marks the action as requires_execution."
            />
          </div>
          {!canWrite && (
            <div className="mt-4 rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-secondary">
              This principal lacks <code>tenant.connector.write</code>. Config
              proposals, OMS credential rotation, and safe test actions are
              disabled in the UI.
            </div>
          )}
        </Card>

        <OmsCredentialCard
          state={omsCredentialState}
          pendingCount={omsCredentialPendingCount}
          canWrite={canWrite}
          onManage={() => setModal({ type: "credential" })}
        />
      </div>

      {notice && <ProposedNotice message={notice} onDismiss={() => setNotice(null)} />}

      {isLoading && <LoadingState label="Loading connector command center..." />}
      {error && !isLoading && (
        <ErrorState
          title="Connector command center unavailable"
          message={error}
          onAction={reload}
        />
      )}

      {!isLoading && !error && cards.length === 0 && (
        <EmptyState
          title="No connector tools available"
          message="No tenant-facing connector tools were found for this workspace."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}

      {!isLoading && !error && cards.length > 0 && (
        <div className="space-y-6">
          <section>
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-[20px] font-semibold text-ink-primary">
                  Connector Tools
                </h2>
                <p className="text-[13px] text-ink-secondary">
                  Each card shows the live governed state for a single autonomous
                  execution tool.
                </p>
              </div>
              <div className="flex items-center gap-2">
                {canWrite && (
                  <button
                    type="button"
                    onClick={() => setModal({ type: "add_custom" })}
                    className="cc-btn cc-btn-secondary"
                  >
                    <PlugZap size={14} strokeWidth={1.8} />
                    Add custom connector
                  </button>
                )}
                <button
                  type="button"
                  onClick={reload}
                  className="cc-btn cc-btn-secondary"
                >
                  <RefreshCw size={14} strokeWidth={1.8} />
                  Refresh
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
              {cards.map((card) => {
                const isCustom = "isCustom" in card.tool && card.tool.isCustom;
                const connectorId = card.tool.toolName.includes(".")
                  ? card.tool.toolName.split(".").slice(0, -1).join(".")
                  : card.tool.toolName;
                return (
                  <ConnectorToolCard
                    key={card.tool.toolName}
                    card={card}
                    canWrite={canWrite}
                    testState={testStates[card.tool.toolName] ?? null}
                    onConfigure={() =>
                      setModal({
                        type: "configure",
                        tool: card.tool,
                        connector: card.connector,
                      })
                    }
                    onTest={() => runTest(card.tool.toolName)}
                    onManageCredential={
                      isCustom
                        ? () =>
                            setModal({
                              type: "custom_credential",
                              connectorId,
                              toolName: card.tool.toolName,
                              label: card.tool.label,
                            })
                        : undefined
                    }
                  />
                );
              })}
            </div>
          </section>

          <section>
            <div className="mb-3">
              <h2 className="text-[20px] font-semibold text-ink-primary">MCP Servers</h2>
              <p className="text-[13px] text-ink-secondary">
                Connect any MCP-compatible server your tenant uses. Tools are classified and governed per the existing approval model.
              </p>
            </div>
            <McpConnectorView tenantId={tenantId} canWrite={canWrite} />
          </section>

          <section>
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-[20px] font-semibold text-ink-primary">Policies</h2>
                <p className="text-[13px] text-ink-secondary">
                  Execution policies govern when connectors may fire autonomously.
                  All policy changes are dual-controlled.
                </p>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Link
                href="/dashboard/action-policy"
                className="group flex flex-col gap-2 rounded-lg border border-border-subtle bg-surface p-4 transition-colors hover:border-border-defined hover:bg-surface-raised"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Shield className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
                    <span className="text-[13px] font-semibold text-ink-primary">
                      Action Policy
                    </span>
                  </div>
                  <ArrowUpRight
                    className="h-3.5 w-3.5 text-ink-tertiary transition-colors group-hover:text-ink-secondary"
                    strokeWidth={1.8}
                  />
                </div>
                <p className="text-[12px] text-ink-secondary">
                  View and propose changes to the action_tools policy — governs
                  refund, warranty, replacement, and repair execution rules.
                </p>
                <StatusBadge
                  label={
                    (data?.policies ?? []).some(
                      (p) => p.policy_type === ACTION_TOOLS_POLICY_TYPE && p.status === "active"
                    )
                      ? "Active"
                      : "Not configured"
                  }
                  tone={
                    (data?.policies ?? []).some(
                      (p) => p.policy_type === ACTION_TOOLS_POLICY_TYPE && p.status === "active"
                    )
                      ? "success"
                      : "warning"
                  }
                  icon={Shield}
                />
              </Link>

              <Link
                href="/dashboard/governance"
                className="group flex flex-col gap-2 rounded-lg border border-border-subtle bg-surface p-4 transition-colors hover:border-border-defined hover:bg-surface-raised"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Sliders className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
                    <span className="text-[13px] font-semibold text-ink-primary">
                      AI Behavior Rules
                    </span>
                  </div>
                  <ArrowUpRight
                    className="h-3.5 w-3.5 text-ink-tertiary transition-colors group-hover:text-ink-secondary"
                    strokeWidth={1.8}
                  />
                </div>
                <p className="text-[12px] text-ink-secondary">
                  Manage all governance policies — resolution autonomy, taxonomy,
                  extraction schema, and more. All changes are governed by dual control.
                </p>
                <StatusBadge
                  label={`${(data?.policies ?? []).length} polic${(data?.policies ?? []).length === 1 ? "y" : "ies"} configured`}
                  tone="info"
                  icon={Sliders}
                />
              </Link>
            </div>
          </section>

          <section>
            <div className="mb-3">
              <h2 className="text-[20px] font-semibold text-ink-primary">
                Pending Approvals
              </h2>
              <p className="text-[13px] text-ink-secondary">
                Connector and OMS credential changes land here for a separate
                approver. Server-side dual control still enforces the separation of
                duty.
              </p>
            </div>
            <Card className="p-0">
              <ConfigChangeApprovals embedded changeKind="connector" />
            </Card>
          </section>
        </div>
      )}

      {modal.type === "configure" && (
        <Modal onClose={() => setModal({ type: "none" })}>
          <ConnectorProposeForm
            tool={modal.tool}
            connector={modal.connector}
            onProposed={() => {
              setNotice(
                `${modal.tool.label} change proposed. It now awaits approval in Pending Approvals.`
              );
              setModal({ type: "none" });
              reload();
            }}
          />
        </Modal>
      )}

      {modal.type === "credential" && (
        <Modal onClose={() => setModal({ type: "none" })}>
          <OmsCredentialForm
            tenantId={tenantId}
            currentState={omsCredentialState}
            canWrite={canWrite}
            pendingCount={omsCredentialPendingCount}
            onProposed={() => {
              setNotice(
                "OMS credential update proposed. It now awaits approval in Pending Approvals."
              );
              setModal({ type: "none" });
              reload();
            }}
          />
        </Modal>
      )}

      {modal.type === "add_custom" && (
        <Modal onClose={() => setModal({ type: "none" })}>
          <AddCustomConnectorForm
            onProposed={(toolName) => {
              setNotice(
                `Custom connector "${toolName}" proposed. It now awaits approval in Pending Approvals.`
              );
              setModal({ type: "none" });
              reload();
            }}
          />
        </Modal>
      )}

      {modal.type === "custom_credential" && (
        <Modal onClose={() => setModal({ type: "none" })}>
          <ConnectorCredentialForm
            tenantId={tenantId}
            toolName={modal.toolName}
            connectorId={modal.connectorId}
            label={modal.label}
            canWrite={canWrite}
            onProposed={() => {
              setNotice(
                `Credential for "${modal.label}" proposed. It now awaits approval in Pending Approvals.`
              );
              setModal({ type: "none" });
              reload();
            }}
          />
        </Modal>
      )}
    </main>
  );
}

function AddCustomConnectorForm({
  onProposed,
}: {
  onProposed: (toolName: string) => void;
}) {
  const [toolName, setToolName] = useState("");
  const [connectorType, setConnectorType] = useState("record");
  const [httpMethod, setHttpMethod] = useState("POST");
  const [endpointTemplate, setEndpointTemplate] = useState("");
  const [idempotencyHeader, setIdempotencyHeader] = useState("Idempotency-Key");
  const [successStatusCodes, setSuccessStatusCodes] = useState("200, 201, 202");
  const [fieldMappings, setFieldMappings] = useState<KeyValueRow[]>([createRow()]);
  const [responseParse, setResponseParse] = useState<KeyValueRow[]>([createRow()]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const endpointPreview = sanitizeEndpointDisplay(endpointTemplate);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    const trimmedName = toolName.trim();
    if (!trimmedName) {
      setError("Tool name is required.");
      setIsSubmitting(false);
      return;
    }
    try {
      const parsedUrl = parseHttpsUrl(endpointTemplate);
      const body = buildConnectorChangePayload({
        connector_type: connectorType,
        tool_name: trimmedName,
        http_method: httpMethod,
        endpoint_template: endpointTemplate.trim(),
        endpoint_host: parsedUrl.host,
        field_mappings: rowsToRecord(fieldMappings),
        response_parse: rowsToRecord(responseParse),
        idempotency_header_name: idempotencyHeader.trim(),
        success_status_codes: parseStatusCodes(successStatusCodes),
        status: "active",
      });
      await proposeConfigChangeRequest(body);
      onProposed(trimmedName);
    } catch (caught: unknown) {
      setError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h2 className="font-display text-[24px] font-semibold text-ink-primary">
          Add Custom Connector
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-ink-secondary">
          Define a governed connector for any integration your tenant needs.
          Domain-agnostic: bank account.freeze, telecom service.suspend, or any
          custom HTTP endpoint. The tool name you choose here becomes the
          identifier the agent uses to call this action.
        </p>
      </div>

      {error && <FormError message={error} />}

      <Fieldset legend="Identity">
        <Text
          label="Tool name (e.g. account.freeze)"
          name="tool_name"
          value={toolName}
          onChange={setToolName}
          placeholder="account.freeze"
          required
        />
        <Select
          label="Connector type"
          name="connector_type"
          value={connectorType}
          options={[...CONNECTOR_TYPE_OPTIONS]}
          onChange={setConnectorType}
        />
      </Fieldset>

      <Fieldset legend="Endpoint">
        <Select
          label="HTTP method"
          name="http_method"
          value={httpMethod}
          options={[...HTTP_METHOD_OPTIONS]}
          onChange={setHttpMethod}
        />
        <Text
          label="Endpoint URL"
          name="endpoint_template"
          value={endpointTemplate}
          onChange={setEndpointTemplate}
          placeholder="https://api.tenant.example/accounts/freeze"
          required
        />
        <Field label="Validated host preview" value={endpointPreview} />
        <Text
          label="Idempotency header"
          name="idempotency_header_name"
          value={idempotencyHeader}
          onChange={setIdempotencyHeader}
          required
        />
        <Text
          label="Success status codes"
          name="success_status_codes"
          value={successStatusCodes}
          onChange={setSuccessStatusCodes}
          placeholder="200, 201, 202"
          required
        />
      </Fieldset>

      <Fieldset legend="Field mappings">
        <p className="text-[13px] text-ink-secondary">
          Map Operious action payload fields to the target API schema.
        </p>
        <MappingEditor rows={fieldMappings} onChange={setFieldMappings} />
      </Fieldset>

      <Fieldset legend="Response parsing">
        <p className="text-[13px] text-ink-secondary">
          Map tenant response fields for provider id, status, and errors.
        </p>
        <MappingEditor rows={responseParse} onChange={setResponseParse} />
      </Fieldset>

      <Submit isSubmitting={isSubmitting} label="Propose custom connector" />
    </form>
  );
}

const GENERIC_AUTH_TYPES = ["bearer", "api_key", "basic"] as const;

function ConnectorCredentialForm({
  tenantId,
  toolName,
  connectorId,
  label,
  canWrite,
  onProposed,
}: {
  tenantId: string | null;
  toolName: string;
  connectorId: string;
  label: string;
  canWrite: boolean;
  onProposed: () => void;
}) {
  const [authType, setAuthType] =
    useState<(typeof GENERIC_AUTH_TYPES)[number]>("bearer");
  const [token, setToken] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenantId) {
      setError("Tenant scope is missing, so credential submission is unavailable.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const request = buildOmsCredentialRequest({ authType, token, apiKey, username, password });
      await proposeConnectorCredentials(tenantId, toolName, request);
      onProposed();
    } catch (caught: unknown) {
      setError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h2 className="font-display text-[24px] font-semibold text-ink-primary">
          Manage Credential: {label}
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-ink-secondary">
          Write-only. The credential is encrypted via OPCRED2 immediately on
          submission and stored per-connector. Values are never returned by the
          API. A separate approver must approve this change request.
        </p>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-secondary">
        <Field label="Connector ID" value={connectorId} />
        <Field label="Tool name" value={toolName} />
      </div>

      {error && <FormError message={error} />}

      <Fieldset legend="Credential">
        <Select
          label="Auth type"
          name="auth_type"
          value={authType}
          options={[...GENERIC_AUTH_TYPES]}
          onChange={(value) =>
            setAuthType(value as (typeof GENERIC_AUTH_TYPES)[number])
          }
        />
        {authType === "bearer" && (
          <WriteOnlyInput
            name="token"
            label="Bearer token"
            value={token}
            onChange={setToken}
          />
        )}
        {authType === "api_key" && (
          <WriteOnlyInput
            name="api_key"
            label="API key"
            value={apiKey}
            onChange={setApiKey}
          />
        )}
        {authType === "basic" && (
          <>
            <WriteOnlyInput
              name="username"
              label="Username"
              value={username}
              onChange={setUsername}
            />
            <WriteOnlyInput
              name="password"
              label="Password"
              value={password}
              onChange={setPassword}
            />
          </>
        )}
      </Fieldset>

      <button
        type="submit"
        disabled={!canWrite || !tenantId || isSubmitting}
        className="inline-flex min-h-11 items-center justify-center rounded bg-gold-primary px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-50"
      >
        {isSubmitting ? "Proposing..." : "Propose credential"}
      </button>
    </form>
  );
}

function OmsCredentialCard({
  state,
  pendingCount,
  canWrite,
  onManage,
}: {
  state: TenantChannelConfiguration | null;
  pendingCount: number;
  canWrite: boolean;
  onManage: () => void;
}) {
  const configured = state !== null;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>OMS Credentials</CardTitle>
          <CardDescription>
            Write-only credential state for OMS-backed execution tools. Credential
            values are never read back into the browser.
          </CardDescription>
        </div>
        <StatusBadge
          label={configured ? "Configured" : "Not configured"}
          tone={configured ? "success" : "warning"}
          icon={KeyRound}
        />
      </CardHeader>
      <div className="grid gap-2 text-[13px] text-ink-secondary">
        <Field
          label="Credential state"
          value={configured ? "Configured" : "No OMS credential record"}
        />
        <Field
          label="Last updated"
          value={state?.credential_rotated_at ? formatDate(state.credential_rotated_at) : "Never"}
        />
        <Field label="Status" value={state?.status ?? "not_configured"} />
        <Field
          label="Pending approvals"
          value={pendingCount > 0 ? `${pendingCount} awaiting approval` : "None"}
        />
      </div>
      <div className="mt-4 rounded-lg border border-gold-primary/30 bg-gold-bg px-3 py-2 text-[12px] leading-relaxed text-ink-primary">
        This UI is write-only by design. The current backend exposes OMS
        credential lifecycle storage and apply logic, but the tenant propose route
        for <code>credential_update</code> is not yet published at the HTTP layer,
        so submission remains blocked from the browser.
      </div>
      <div className="mt-4">
        <button
          type="button"
          onClick={onManage}
          disabled={!canWrite}
          className="cc-btn cc-btn-secondary disabled:opacity-50"
        >
          <KeyRound size={14} strokeWidth={1.8} />
          Manage OMS credential
        </button>
      </div>
    </Card>
  );
}

function ConnectorToolCard({
  card,
  canWrite,
  testState,
  onConfigure,
  onTest,
  onManageCredential,
}: {
  card: ConnectorCardView;
  canWrite: boolean;
  testState: TestState | null;
  onConfigure: () => void;
  onTest: () => void;
  onManageCredential?: () => void;
}) {
  const statusMeta = connectorStatusMeta(card.status);
  const connector = card.connector;

  return (
    <Card hover>
      <CardHeader>
        <div>
          <CardTitle>{card.tool.label}</CardTitle>
          <CardDescription>{card.tool.summary}</CardDescription>
        </div>
        <StatusBadge
          label={statusMeta.label}
          tone={statusMeta.tone}
          icon={statusMeta.icon}
        />
      </CardHeader>

      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Tool name" value={card.tool.toolName} />
        <Field
          label="Connector type"
          value={connector?.connector_type ?? card.tool.defaultConnectorType}
        />
        <Field label="Endpoint host" value={card.endpointPreview} />
        <Field label="HTTP method" value={connector?.http_method ?? "POST"} />
        <Field
          label="Idempotency header"
          value={connector?.idempotency_header_name ?? "Idempotency-Key"}
        />
        <Field label="Version" value={connector ? `v${connector.version}` : "—"} />
        <Field label="Last configured by" value={connector?.configured_by ?? "—"} />
        <Field label="Source approval" value={connector?.source_approval_id ?? "—"} />
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-3">
        <GateBadge
          label="Connector configured"
          active={card.gateState.connectorConfigured}
        />
        <GateBadge
          label="Action policy active"
          active={card.gateState.actionPolicyActive}
        />
        <GateBadge
          label="Taxonomy requires execution"
          active={card.gateState.taxonomyRequiresExecution}
        />
      </div>

      <div className="mt-3 rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-secondary">
        <div className="font-medium text-ink-primary">
          {card.gateState.armed ? "Execution armed" : "Execution not armed"}
        </div>
        <div className="mt-1">
          {!card.gateState.actionPolicyActive
            ? card.gateState.policyHint
            : !card.gateState.taxonomyRequiresExecution
              ? card.gateState.taxonomyHint
              : card.gateState.connectorConfigured
                ? "All three gates are present. Autonomous execution can proceed only within policy."
                : "A live connector config is still required before autonomous execution can occur."}
        </div>
      </div>

      {card.pendingRequestCount > 0 && (
        <div className="mt-3 rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] text-ink-secondary">
          {card.pendingRequestCount} connector change
          {card.pendingRequestCount === 1 ? "" : "s"} awaiting separate approval.
        </div>
      )}

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          onClick={onConfigure}
          disabled={!canWrite}
          className="cc-btn cc-btn-secondary disabled:opacity-50"
        >
          <PlugZap size={14} strokeWidth={1.8} />
          Propose config change
        </button>
        <button
          type="button"
          onClick={onTest}
          disabled={!canWrite || connector === null || testState?.busy === true}
          className="cc-btn cc-btn-secondary disabled:opacity-50"
        >
          <TestTubeDiagonal size={14} strokeWidth={1.8} />
          {testState?.busy ? "Testing..." : "Test Connection"}
        </button>
        {onManageCredential && (
          <button
            type="button"
            onClick={onManageCredential}
            disabled={!canWrite}
            className="cc-btn cc-btn-secondary disabled:opacity-50"
          >
            <KeyRound size={14} strokeWidth={1.8} />
            Manage credential
          </button>
        )}
      </div>

      {testState && <ConnectorTestResult result={testState} />}

      <TechnicalDetails
        label="Show connector details"
        openLabel="Hide connector details"
      >
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-[12px] font-medium text-ink-primary">
              Field mappings
            </p>
            <CodeAsReadableText
              data={connector?.field_mappings ?? asRecord(card.pendingProposal?.field_mappings)}
            />
          </div>
          <div>
            <p className="mb-2 text-[12px] font-medium text-ink-primary">
              Response parsing
            </p>
            <CodeAsReadableText
              data={connector?.response_parse ?? asRecord(card.pendingProposal?.response_parse)}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <DownloadableLog
              data={connector ?? card.pendingProposal ?? {}}
              filename={`${card.tool.toolName.replace(/\./g, "-")}-connector.json`}
              label="Download connector detail"
            />
          </div>
        </div>
      </TechnicalDetails>
    </Card>
  );
}

function ConnectorTestResult({ result }: { result: TestState }) {
  if (result.error) {
    return (
      <div className="mt-4 rounded-lg border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
        Safe test failed: {result.error}
      </div>
    );
  }
  if (!result.data) return null;

  return (
    <div className="mt-4 rounded-lg border border-border-subtle bg-surface-raised p-3">
      <div className="mb-3 flex items-center gap-2">
        <Shield className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
        <span className="text-[13px] font-medium text-ink-primary">
          Safe test result
        </span>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <Field label="Reachable" value={result.data.reachable ? "Yes" : "No"} />
        <Field
          label="TLS verified"
          value={result.data.tls_verified ? "Yes" : "No"}
        />
        <Field
          label="Config valid"
          value={result.data.config_valid ? "Yes" : "No"}
        />
        <Field label="HTTP probe" value={result.data.http_probe} />
        <Field
          label="Validated host"
          value={result.data.validated_host ?? "No host validated"}
        />
      </div>
    </div>
  );
}

function ConnectorProposeForm({
  tool,
  connector,
  onProposed,
}: {
  tool: ConnectorToolDefinition | CustomConnectorTool;
  connector: TenantConnectorConfiguration | null;
  onProposed: () => void;
}) {
  const [connectorType, setConnectorType] = useState(
    connector?.connector_type ?? tool.defaultConnectorType
  );
  const [httpMethod, setHttpMethod] = useState(connector?.http_method ?? "POST");
  const [endpointTemplate, setEndpointTemplate] = useState(
    connector?.endpoint_template ?? ""
  );
  const [idempotencyHeader, setIdempotencyHeader] = useState(
    connector?.idempotency_header_name ?? "Idempotency-Key"
  );
  const [successStatusCodes, setSuccessStatusCodes] = useState(
    (connector?.success_status_codes ?? [200]).join(", ")
  );
  const [status, setStatus] = useState(connector?.status ?? "active");
  const [fieldMappings, setFieldMappings] = useState(
    recordToRows(connector?.field_mappings ?? {})
  );
  const [responseParse, setResponseParse] = useState(
    recordToRows(connector?.response_parse ?? {})
  );
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const endpointPreview = sanitizeEndpointDisplay(endpointTemplate);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      const parsedUrl = parseHttpsUrl(endpointTemplate);
      const body = buildConnectorChangePayload({
        connector_type: connectorType,
        tool_name: tool.toolName,
        http_method: httpMethod,
        endpoint_template: endpointTemplate.trim(),
        endpoint_host: parsedUrl.host,
        field_mappings: rowsToRecord(fieldMappings),
        response_parse: rowsToRecord(responseParse),
        idempotency_header_name: idempotencyHeader.trim(),
        success_status_codes: parseStatusCodes(successStatusCodes),
        status,
      });
      await proposeConfigChangeRequest(body);
      onProposed();
    } catch (caught: unknown) {
      setError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h2 className="font-display text-[24px] font-semibold text-ink-primary">
          {connector ? `Update ${tool.label}` : `Configure ${tool.label}`}
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-ink-secondary">
          This creates a governed connector change request. It is applied only
          after approval by a different principal.
        </p>
      </div>

      {error && <FormError message={error} />}

      <Fieldset legend="Identity">
        <Field label="Tool name" value={tool.toolName} />
        <Select
          label="Connector type"
          name="connector_type"
          value={connectorType}
          options={[...CONNECTOR_TYPE_OPTIONS]}
          onChange={setConnectorType}
        />
      </Fieldset>

      <Fieldset legend="Endpoint">
        <Select
          label="HTTP method"
          name="http_method"
          value={httpMethod}
          options={[...HTTP_METHOD_OPTIONS]}
          onChange={setHttpMethod}
        />
        <Text
          label="Endpoint URL"
          name="endpoint_template"
          value={endpointTemplate}
          onChange={setEndpointTemplate}
          placeholder="https://api.tenant.example/remedies/refunds"
          required
        />
        <Field label="Validated host preview" value={endpointPreview} />
        <Text
          label="Idempotency header"
          name="idempotency_header_name"
          value={idempotencyHeader}
          onChange={setIdempotencyHeader}
          required
        />
        <Text
          label="Success status codes"
          name="success_status_codes"
          value={successStatusCodes}
          onChange={setSuccessStatusCodes}
          placeholder="200, 201, 202"
          required
        />
        <Select
          label="Record status"
          name="status"
          value={status}
          options={[...CONNECTOR_STATUS_OPTIONS]}
          onChange={setStatus}
        />
      </Fieldset>

      <Fieldset legend="Field mappings">
        <p className="text-[13px] text-ink-secondary">
          Map Operious action payload fields to the tenant API schema using
          dot-paths such as <code>payload.order_id</code>.
        </p>
        <MappingEditor rows={fieldMappings} onChange={setFieldMappings} />
      </Fieldset>

      <Fieldset legend="Response parsing">
        <p className="text-[13px] text-ink-secondary">
          Map tenant response fields used for provider id, provider status, and
          provider errors.
        </p>
        <MappingEditor rows={responseParse} onChange={setResponseParse} />
      </Fieldset>

      <Submit isSubmitting={isSubmitting} label="Propose config change" />
    </form>
  );
}

function OmsCredentialForm({
  tenantId,
  currentState,
  canWrite,
  pendingCount,
  onProposed,
}: {
  tenantId: string | null;
  currentState: TenantChannelConfiguration | null;
  canWrite: boolean;
  pendingCount: number;
  onProposed: () => void;
}) {
  const [authType, setAuthType] = useState<(typeof OMS_AUTH_TYPES)[number]>("bearer");
  const [token, setToken] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const rotationBlocked = currentState?.status === "active";

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenantId) {
      setError("Tenant scope is missing, so OMS credential submission is unavailable.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const request = buildOmsCredentialRequest({
        authType,
        token,
        apiKey,
        username,
        password,
      });
      await proposeConnectorCredentials(
        tenantId,
        OMS_CREDENTIAL_TOOL_NAME,
        request
      );
      onProposed();
    } catch (caught: unknown) {
      setError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h2 className="font-display text-[24px] font-semibold text-ink-primary">
          OMS Credential
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-ink-secondary">
          The form is write-only. Existing values are never displayed, never
          pre-populated, and never returned from the API.
        </p>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
        <div className="grid gap-2 md:grid-cols-3">
          <Field
            label="Configured"
            value={currentState ? "Yes" : "No"}
          />
          <Field
            label="Last updated"
            value={
              currentState?.credential_rotated_at
                ? formatDate(currentState.credential_rotated_at)
                : "Never"
            }
          />
          <Field label="Status" value={currentState?.status ?? "not_configured"} />
        </div>
      </div>

      {error && <FormError message={error} />}

      <div className="rounded-lg border border-gold-primary/30 bg-gold-bg px-3 py-2 text-[13px] leading-relaxed text-ink-primary">
        Pending approvals: {pendingCount}. Submission creates a governed
        <code>credential_update</code> proposal only. A separate approver still
        approves it through the existing dual-control flow, and the credential
        value is never read back to the browser.
      </div>

      {rotationBlocked && (
        <div className="rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-secondary">
          An active OMS credential already exists for this tenant. The existing
          backend service still blocks active-credential rotation, so this form
          only supports the pending-validation onboarding path.
        </div>
      )}

      <Fieldset legend="Credential">
        <Select
          label="Auth type"
          name="auth_type"
          value={authType}
          options={[...OMS_AUTH_TYPES]}
          onChange={(value) => setAuthType(value as (typeof OMS_AUTH_TYPES)[number])}
        />
        {authType === "bearer" && (
          <WriteOnlyInput
            name="token"
            label="Bearer token"
            value={token}
            onChange={setToken}
          />
        )}
        {authType === "api_key" && (
          <WriteOnlyInput
            name="api_key"
            label="API key"
            value={apiKey}
            onChange={setApiKey}
          />
        )}
        {authType === "basic" && (
          <>
            <WriteOnlyInput
              name="username"
              label="Username"
              value={username}
              onChange={setUsername}
            />
            <WriteOnlyInput
              name="password"
              label="Password"
              value={password}
              onChange={setPassword}
            />
          </>
        )}
      </Fieldset>

      <button
        type="submit"
        disabled={!canWrite || !tenantId || rotationBlocked || isSubmitting}
        className="inline-flex min-h-11 items-center justify-center rounded bg-gold-primary px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-50"
        title={
          !canWrite
            ? "This principal lacks tenant.connector.write."
            : rotationBlocked
              ? "Active OMS credential rotation is not yet supported by the backend service."
              : undefined
        }
      >
        {isSubmitting ? "Proposing..." : "Propose credential update"}
      </button>
    </form>
  );
}

// ─── Action-policy editor ─────────────────────────────────────────────────

export function ActionPolicyView() {
  const [modal, setModal] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => listGovernancePolicies(), []);
  const { data, error, isLoading, reload } = useApiResource(load);
  const actionPolicy = useMemo(
    () =>
      (data?.items ?? []).find(
        (policy) => policy.policy_type === ACTION_TOOLS_POLICY_TYPE
      ) ?? null,
    [data]
  );

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <Header
        eyebrow="GOVERNANCE · ACTION POLICY"
        title="Action Policy"
        actionLabel="Propose policy change"
        onAction={() => setModal(true)}
      />
      <GovernedNotice />
      {notice && <ProposedNotice message={notice} onDismiss={() => setNotice(null)} />}
      {isLoading && <LoadingState />}
      {error && !isLoading && (
        <ErrorState title="Action policy unavailable" message={error} onAction={reload} />
      )}
      {!isLoading && !error && !actionPolicy && (
        <EmptyState
          title="No action_tools policy configured"
          message="Propose an action_tools policy to govern warranty, replacement, refund, and warehouse tools."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}
      {!isLoading && !error && actionPolicy && <ActionPolicyCard policy={actionPolicy} />}

      {modal && (
        <Modal onClose={() => setModal(false)}>
          <ActionPolicyForm
            policy={actionPolicy}
            onProposed={() => {
              setNotice(
                "Action policy change proposed. It now awaits approval by another principal."
              );
              setModal(false);
              reload();
            }}
          />
        </Modal>
      )}
    </main>
  );
}

function ActionPolicyCard({ policy }: { policy: TenantGovernancePolicy }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>action_tools</CardTitle>
          <CardDescription>
            Governs whether autonomous execution is allowed, denied, or requires
            approval for each action tool.
          </CardDescription>
        </div>
        <StatusBadge label={`v${policy.version} · ${policy.status}`} tone="info" />
      </CardHeader>
      <div className="grid gap-2 md:grid-cols-2">
        <Field label="Approved by" value={policy.approved_by} />
        <Field label="Effective from" value={formatDate(policy.effective_from)} />
      </div>
      <TechnicalDetails label="Show policy parameters" openLabel="Hide policy parameters">
        <CodeAsReadableText data={policy.parameters} />
        <div className="mt-3">
          <DownloadableLog
            data={policy.parameters}
            filename="action-tools-policy.json"
            label="Download policy parameters"
          />
        </div>
      </TechnicalDetails>
    </Card>
  );
}

function ActionPolicyForm({
  policy,
  onProposed,
}: {
  policy: TenantGovernancePolicy | null;
  onProposed: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const existing = readExistingActionPolicy(policy);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      const refundConfidenceRaw = String(
        form.get("refund_confidence_gte") || ""
      ).trim();
      const body = buildActionPolicyChangePayload({
        policyId: policy?.policy_id,
        effectiveFrom: policy
          ? undefined
          : new Date(String(form.get("effective_from") || "")).toISOString(),
        warrantyConfidenceGte: Number(form.get("warranty_confidence_gte")),
        warrantyIssueCategories: parseList(
          String(form.get("warranty_issue_category_in") || "")
        ),
        warrantyElse: String(
          form.get("warranty_else") || "require_approval"
        ) as PolicyDecision,
        replacementAlways: String(
          form.get("replacement_always") || "require_approval"
        ) as PolicyDecision,
        refundAmountCentsLte: Number(form.get("refund_amount_cents_lte")),
        refundConfidenceGte:
          refundConfidenceRaw === "" ? null : Number(refundConfidenceRaw),
        refundElse: String(
          form.get("refund_else") || "require_approval"
        ) as PolicyDecision,
        warehouseAllowSeverities: parseList(
          String(form.get("warehouse_allow_severity_in") || "")
        ),
        warehouseRequireApprovalSeverities: parseList(
          String(form.get("warehouse_require_approval_severity_in") || "")
        ),
      });
      await proposeConfigChangeRequest(body);
      onProposed();
    } catch (caught: unknown) {
      setError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <h2 className="font-display text-[24px] font-semibold text-ink-primary">
        {policy ? "Propose Action Policy Change" : "Propose Action Policy"}
      </h2>
      <p className="text-[13px] leading-relaxed text-ink-secondary">
        Governed change only. A different principal must approve it before it can
        apply.
      </p>
      {error && <FormError message={error} />}
      {!policy && (
        <Text
          name="effective_from"
          label="Effective from"
          type="datetime-local"
          defaultValue={nowLocal()}
          required
        />
      )}

      <Fieldset legend="Refund">
        <Text
          name="refund_amount_cents_lte"
          label="Refund ceiling (cents)"
          type="number"
          defaultValue={String(existing.refundAmountCentsLte ?? 5000)}
          required
        />
        <Text
          name="refund_confidence_gte"
          label="Refund confidence threshold (0–1, optional)"
          type="number"
          defaultValue={
            existing.refundConfidenceGte == null
              ? ""
              : String(existing.refundConfidenceGte)
          }
        />
        <Select
          name="refund_else"
          label="Otherwise"
          defaultValue={existing.refundElse ?? "require_approval"}
          options={["require_approval", "deny"]}
        />
      </Fieldset>

      <Fieldset legend="Warranty">
        <Text
          name="warranty_confidence_gte"
          label="Confidence threshold (0–1)"
          type="number"
          defaultValue={String(existing.warrantyConfidenceGte ?? 0.8)}
          required
        />
        <Text
          name="warranty_issue_category_in"
          label="Warranty categories (comma separated)"
          defaultValue={(existing.warrantyIssueCategories ?? []).join(", ")}
          required
        />
        <Select
          name="warranty_else"
          label="Otherwise"
          defaultValue={existing.warrantyElse ?? "require_approval"}
          options={["require_approval", "deny"]}
        />
      </Fieldset>

      <Fieldset legend="Replacement">
        <Select
          name="replacement_always"
          label="Replacement rule (always)"
          defaultValue={existing.replacementAlways ?? "require_approval"}
          options={[...POLICY_DECISION_VALUES]}
        />
      </Fieldset>

      <Fieldset legend="Warehouse repair">
        <Text
          name="warehouse_allow_severity_in"
          label="Auto-allow severities (comma separated)"
          defaultValue={(existing.warehouseAllowSeverities ?? []).join(", ")}
          required
        />
        <Text
          name="warehouse_require_approval_severity_in"
          label="Require-approval severities (comma separated)"
          defaultValue={(existing.warehouseRequireApprovalSeverities ?? []).join(", ")}
          required
        />
      </Fieldset>

      <Submit isSubmitting={isSubmitting} label="Propose policy change" />
    </form>
  );
}

// ─── Shared primitives ────────────────────────────────────────────────────

function Header({
  eyebrow,
  title,
  actionLabel,
  onAction,
}: {
  eyebrow: string;
  title: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <>
      <div className="eyebrow mb-2 text-ink-tertiary">{eyebrow}</div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="font-display text-[32px] font-semibold text-ink-primary">
          {title}
        </h1>
        {actionLabel && onAction && (
          <button
            type="button"
            onClick={onAction}
            className="cc-btn cc-btn-secondary"
          >
            {actionLabel}
          </button>
        )}
      </div>
    </>
  );
}

function GateExplainer({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised px-3 py-3">
      <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {title}
      </div>
      <div className="mt-1 text-[13px] text-ink-secondary">{body}</div>
    </div>
  );
}

function GateBadge({ label, active }: { label: string; active: boolean }) {
  return (
    <StatusBadge
      label={`${label}: ${active ? "yes" : "no"}`}
      tone={active ? "success" : "warning"}
      icon={active ? CheckCircle2 : CircleAlert}
      className="justify-center"
    />
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </div>
      <div className="mt-1 break-words text-[13px] leading-relaxed text-ink-secondary">
        {value || "—"}
      </div>
    </div>
  );
}

function Modal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 sm:p-6">
      <div className="max-h-[88dvh] w-full max-w-4xl overflow-y-auto rounded-lg border border-border-subtle bg-surface p-4 shadow-elevated sm:p-6">
        <div className="mb-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle text-ink-tertiary hover:text-ink-primary"
            aria-label="Close modal"
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Fieldset({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 rounded-lg border border-border-subtle bg-surface-raised p-4">
      <legend className="px-1 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-tertiary">
        {legend}
      </legend>
      {children}
    </fieldset>
  );
}

function Text({
  label,
  name,
  type = "text",
  value,
  defaultValue,
  onChange,
  placeholder,
  required = false,
}: {
  label: string;
  name: string;
  type?: string;
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <input
        name={name}
        type={type}
        step={type === "number" ? "any" : undefined}
        value={value}
        defaultValue={defaultValue}
        onChange={onChange ? (event) => onChange(event.target.value) : undefined}
        placeholder={placeholder}
        required={required}
        className="h-11 w-full rounded border border-border-subtle bg-surface px-3 text-[14px] text-ink-primary focus:border-gold-primary focus:outline-none sm:h-10"
      />
    </label>
  );
}

function WriteOnlyInput({
  name,
  label,
  value,
  onChange,
}: {
  name: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <input
        name={name}
        type="password"
        autoComplete="new-password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-full rounded border border-border-subtle bg-surface px-3 text-[14px] text-ink-primary focus:border-gold-primary focus:outline-none sm:h-10"
      />
    </label>
  );
}

function Select({
  label,
  name,
  value,
  defaultValue,
  options,
  onChange,
}: {
  label: string;
  name: string;
  value?: string;
  defaultValue?: string;
  options: string[];
  onChange?: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <select
        name={name}
        value={value}
        defaultValue={defaultValue}
        onChange={onChange ? (event) => onChange(event.target.value) : undefined}
        className="h-11 w-full rounded border border-border-subtle bg-surface px-3 text-[14px] text-ink-primary focus:border-gold-primary focus:outline-none sm:h-10"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function MappingEditor({
  rows,
  onChange,
}: {
  rows: KeyValueRow[];
  onChange: (rows: KeyValueRow[]) => void;
}) {
  const updateRow = (rowId: string, key: "key" | "value", value: string) => {
    onChange(
      rows.map((row) => (row.id === rowId ? { ...row, [key]: value } : row))
    );
  };

  const addRow = () => {
    onChange([...rows, createRow()]);
  };

  const removeRow = (rowId: string) => {
    const remaining = rows.filter((row) => row.id !== rowId);
    onChange(remaining.length > 0 ? remaining : [createRow()]);
  };

  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.id} className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
          <input
            value={row.key}
            onChange={(event) => updateRow(row.id, "key", event.target.value)}
            placeholder="provider_field"
            className="h-10 rounded border border-border-subtle bg-surface px-3 text-[14px] text-ink-primary focus:border-gold-primary focus:outline-none"
          />
          <input
            value={row.value}
            onChange={(event) => updateRow(row.id, "value", event.target.value)}
            placeholder="payload.order_id"
            className="h-10 rounded border border-border-subtle bg-surface px-3 text-[14px] text-ink-primary focus:border-gold-primary focus:outline-none"
          />
          <button
            type="button"
            onClick={() => removeRow(row.id)}
            className="cc-btn cc-btn-secondary"
          >
            Remove
          </button>
        </div>
      ))}
      <button type="button" onClick={addRow} className="cc-btn cc-btn-secondary">
        <Link2 size={14} strokeWidth={1.8} />
        Add mapping
      </button>
    </div>
  );
}

function Submit({ isSubmitting, label }: { isSubmitting: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={isSubmitting}
      className="inline-flex min-h-11 items-center justify-center rounded bg-gold-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-gold-muted disabled:opacity-60"
    >
      {isSubmitting ? "Proposing..." : label}
    </button>
  );
}

export function GovernedNotice() {
  return (
    <div className="mb-4 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] leading-relaxed text-ink-secondary">
      Edits here are governed: they become change requests that stay pending
      until a different principal approves them, then apply.
    </div>
  );
}

export function ProposedNotice({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-md border border-gold-primary/40 bg-gold-bg px-3 py-2 text-[13px] text-ink-primary">
      <span>{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="h-7 rounded border border-border-subtle px-2 text-[12px] text-ink-secondary hover:text-ink-primary"
      >
        Dismiss
      </button>
    </div>
  );
}

function FormError({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
      {message}
    </div>
  );
}

// ─── helpers ──────────────────────────────────────────────────────────────

function buildConnectorCardView({
  tool,
  history,
  pendingRequests,
  policies,
}: {
  tool: ConnectorToolDefinition | CustomConnectorTool;
  history: TenantConnectorConfiguration[];
  pendingRequests: TenantConfigChangeRequest[];
  policies: TenantGovernancePolicy[];
}): ConnectorCardView {
  const connector = selectLatestConnector(history);
  const toolRequests = pendingRequests.filter(
    (request) =>
      request.change_type === "connector" &&
      request.proposed_payload.tool_name === tool.toolName
  );
  const pendingProposal = toolRequests[0]?.proposed_payload ?? null;
  const status = deriveConnectorStatus(connector, toolRequests.length);
  const gateState = deriveGateState(tool.toolName, connector, policies);
  const endpointPreview =
    displayEndpointPreview(connector?.endpoint_template) ??
    displayEndpointPreview(
      typeof pendingProposal?.endpoint_template === "string"
        ? pendingProposal.endpoint_template
        : null
    ) ??
    "No endpoint configured";

  return {
    tool,
    connector,
    pendingRequestCount: toolRequests.length,
    pendingProposal,
    status,
    endpointPreview,
    gateState,
  };
}

function deriveConnectorStatus(
  connector: TenantConnectorConfiguration | null,
  pendingRequestCount: number
): ConnectorCardStatus {
  if (pendingRequestCount > 0) return "pending_approval";
  if (connector?.status === "active") return "active";
  return "inactive";
}

function deriveGateState(
  toolName: string,
  connector: TenantConnectorConfiguration | null,
  policies: TenantGovernancePolicy[]
): GateState {
  const connectorConfigured = connector?.status === "active";
  const actionPolicy = policies.find(
    (policy) =>
      policy.policy_type === ACTION_TOOLS_POLICY_TYPE && policy.status === "active"
  );
  const actionPolicyActive = hasToolPolicyRule(actionPolicy, toolName);
  const taxonomyRequiresExecution = hasTaxonomyExecutionRule(policies, toolName);

  return {
    connectorConfigured,
    actionPolicyActive,
    taxonomyRequiresExecution,
    armed: connectorConfigured && actionPolicyActive && taxonomyRequiresExecution,
    policyHint: actionPolicyActive
      ? "Active action policy rule is present."
      : "This connector needs an action policy before it can be armed.",
    taxonomyHint: taxonomyRequiresExecution
      ? "Resolution taxonomy currently marks this action for execution."
      : "Resolution taxonomy does not currently mark this action as requires_execution.",
  };
}

function hasToolPolicyRule(
  policy: TenantGovernancePolicy | undefined,
  toolName: string
): boolean {
  if (!policy) return false;
  const tools = asRecord(asRecord(policy.parameters).tools);
  return Object.prototype.hasOwnProperty.call(tools, toolName);
}

function hasTaxonomyExecutionRule(
  policies: TenantGovernancePolicy[],
  toolName: string
): boolean {
  const taxonomy = policies.find(
    (policy) =>
      policy.policy_type === RESOLUTION_TAXONOMY_POLICY_TYPE &&
      policy.status === "active"
  );
  if (!taxonomy) return false;
  const categories = Array.isArray(asRecord(taxonomy.parameters).categories)
    ? (asRecord(taxonomy.parameters).categories as unknown[])
    : [];

  return categories.some((category) => {
    const recommendedActions = Array.isArray(asRecord(category).recommended_actions)
      ? (asRecord(category).recommended_actions as unknown[])
      : [];
    return recommendedActions.some((action) => {
      const actionRecord = asRecord(action);
      return (
        actionRecord.tool_name === toolName &&
        actionRecord.requires_execution === true
      );
    });
  });
}

function selectLatestConnector(
  records: TenantConnectorConfiguration[]
): TenantConnectorConfiguration | null {
  if (records.length === 0) return null;
  return [...records].sort((left, right) => {
    if (left.version !== right.version) return right.version - left.version;
    return right.updated_at.localeCompare(left.updated_at);
  })[0]!;
}

function selectOmsCredentialState(
  channels: TenantChannelConfiguration[]
): TenantChannelConfiguration | null {
  const omsChannels = channels.filter((channel) => channel.channel_type === "oms");
  if (omsChannels.length === 0) return null;
  return [...omsChannels].sort((left, right) => {
    const leftDate =
      left.credential_rotated_at ?? left.verified_at ?? left.credential_rotation_expires_at ?? "";
    const rightDate =
      right.credential_rotated_at ?? right.verified_at ?? right.credential_rotation_expires_at ?? "";
    return rightDate.localeCompare(leftDate);
  })[0]!;
}

function connectorStatusMeta(status: ConnectorCardStatus): {
  label: string;
  tone: "success" | "warning" | "neutral";
  icon: typeof CheckCircle2 | typeof CircleAlert | typeof ArrowUpRight;
} {
  if (status === "active") {
    return { label: "Active", tone: "success", icon: CheckCircle2 };
  }
  if (status === "pending_approval") {
    return { label: "Pending approval", tone: "warning", icon: ArrowUpRight };
  }
  return { label: "Inactive", tone: "neutral", icon: CircleAlert };
}

function parseHttpsUrl(value: string): URL {
  const parsed = new URL(value.trim());
  if (parsed.protocol !== "https:") {
    throw new Error("Endpoint URL must use https.");
  }
  return parsed;
}

function sanitizeEndpointDisplay(value: string): string {
  try {
    const parsed = parseHttpsUrl(value);
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return "Enter a valid https URL";
  }
}

function displayEndpointPreview(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return null;
  }
}

function recordToRows(record: Record<string, unknown>): KeyValueRow[] {
  const entries = Object.entries(record).map(([key, value]) => ({
    id: nextRowId(),
    key,
    value: String(value),
  }));
  return entries.length > 0 ? entries : [createRow()];
}

function rowsToRecord(rows: KeyValueRow[]): Record<string, string> {
  const record: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    const value = row.value.trim();
    if (!key || !value) continue;
    record[key] = value;
  }
  return record;
}

function createRow(): KeyValueRow {
  return { id: nextRowId(), key: "", value: "" };
}

function nextRowId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function buildOmsCredentialRequest(input: {
  authType: (typeof OMS_AUTH_TYPES)[number];
  token: string;
  apiKey: string;
  username: string;
  password: string;
}): TenantOmsCredentialRequest {
  const authType = input.authType;
  if (authType === "bearer") {
    return {
      auth_type: authType,
      token: input.token.trim(),
    };
  }
  if (authType === "api_key") {
    return {
      auth_type: authType,
      api_key: input.apiKey.trim(),
    };
  }
  return {
    auth_type: authType,
    username: input.username.trim(),
    password: input.password,
  };
}

function parseStatusCodes(value: string): number[] {
  const codes = value
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((code) => Number.isInteger(code));
  if (codes.length === 0) {
    throw new Error("Enter at least one integer HTTP status code.");
  }
  return codes;
}

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

function nowLocal(): string {
  return new Date().toISOString().slice(0, 16);
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function readExistingActionPolicy(policy: TenantGovernancePolicy | null): ExistingActionPolicy {
  if (!policy) return {};
  const tools = asRecord(asRecord(policy.parameters).tools);
  const warranty = asRecord(tools["warranty.claim"]);
  const warrantyAllow = asRecord(warranty.allow);
  const replacement = asRecord(tools["replacement.order"]);
  const refund = asRecord(tools["refund.request"]);
  const refundAllow = asRecord(refund.allow);
  const warehouse = asRecord(tools["warehouse.repair.report"]);
  const warehouseAllow = asRecord(warehouse.allow);
  const warehouseRequire = asRecord(warehouse.require_approval);
  return {
    warrantyConfidenceGte: asNumber(warrantyAllow.confidence_gte),
    warrantyIssueCategories: asStringList(warrantyAllow.issue_category_in),
    warrantyElse: asDecision(warranty.else),
    replacementAlways: asDecision(replacement.always),
    refundAmountCentsLte:
      asNumber(refundAllow.refund_amount_cents_lte) ??
      asNumber(refundAllow.amount_cents_lte),
    refundConfidenceGte: asNumber(refundAllow.confidence_gte) ?? null,
    refundElse: asDecision(refund.else),
    warehouseAllowSeverities: asStringList(warehouseAllow.severity_in),
    warehouseRequireApprovalSeverities: asStringList(warehouseRequire.severity_in),
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asStringList(value: unknown): string[] | undefined {
  return Array.isArray(value) ? value.map((item) => String(item)) : undefined;
}

function asDecision(value: unknown): PolicyDecision | undefined {
  return POLICY_DECISION_VALUES.includes(value as PolicyDecision)
    ? (value as PolicyDecision)
    : undefined;
}
