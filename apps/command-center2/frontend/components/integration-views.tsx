"use client";

import { useCallback, useState } from "react";
import {
  createChannelConfiguration,
  createSesSelfServiceChannel,
  createWhatsAppSelfServiceChannel,
  formatApiError,
  getApiBaseUrl,
  getConfiguredOperatorLabel,
  getConfiguredPrincipalId,
  getConfiguredTenantId,
  listChannelConfigurations,
  listDeadLetterExecutions,
  listGovernancePolicies,
  listOperationalAlerts,
  listTopologyConfigurations,
  proposeConfigChangeRequest,
  updateSesSelfServiceChannel,
  updateChannelConfiguration,
  updateWhatsAppSelfServiceChannel,
  type ApiPage,
  type DeadLetterExecution,
  type OperationalAlert,
  type TenantChannelConfiguration,
  type TenantGovernancePolicy,
  type TenantSesSelfServiceRequest,
  type TenantTopologyConfiguration,
  type TenantWhatsAppSelfServiceRequest,
} from "@/lib/api";
import { buildGovernancePolicyChangePayload } from "@/lib/config-change-payloads";
import type { AuthSessionState } from "@/lib/use-auth-session";
import { useApiResource } from "@/lib/use-api-resource";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PendingIntegrationState,
} from "@/components/data-state";
import { GovernedNotice, ProposedNotice } from "@/components/connector-config-views";

type RecordListProps<T> = {
  eyebrow: string;
  title: string;
  load: () => Promise<ApiPage<T>>;
  emptyTitle: string;
  emptyMessage: string;
  headerAction?: React.ReactNode;
  renderItem: (item: T) => React.ReactNode;
};

type PolicyModal =
  | { type: "none" }
  | { type: "create" }
  | { type: "edit"; policy: TenantGovernancePolicy };

type ChannelModal =
  | { type: "none" }
  | { type: "create" }
  | { type: "edit"; channel: TenantChannelConfiguration };

type ChannelCredentialField = {
  key: string;
  label: string;
  type: "text" | "password" | "number" | "select";
  placeholder: string;
  required: boolean;
  helpText?: string;
  options?: string[];
};

const CHANNEL_TYPE_LABELS: Record<string, string> = {
  email: "Email (SES)",
  whatsapp: "WhatsApp Business",
  voice: "Voice (Twilio)",
  zendesk: "Zendesk",
  jira: "Jira",
  linear: "Linear",
  shopify: "Shopify",
  shulex: "Shulex",
  lark: "Lark",
};

const CHANNEL_TYPE_OPTIONS = [
  "email",
  "whatsapp",
  "voice",
  "zendesk",
  "jira",
  "linear",
  "shopify",
  "shulex",
  "lark",
];

const CHANNEL_CREDENTIAL_FIELDS: Record<string, ChannelCredentialField[]> = {
  email: [
    {
      key: "mode",
      label: "SES Mode",
      type: "select",
      placeholder: "managed",
      required: true,
      options: ["managed", "byo_role", "byo_access_key"],
    },
    {
      key: "region",
      label: "AWS Region",
      type: "text",
      placeholder: "us-east-1",
      required: true,
    },
    {
      key: "source_email",
      label: "Source Email",
      type: "text",
      placeholder: "support@yourcompany.com",
      required: false,
    },
    {
      key: "source_domain",
      label: "Source Domain",
      type: "text",
      placeholder: "yourcompany.com",
      required: false,
    },
    {
      key: "inbound_address",
      label: "Inbound Address",
      type: "text",
      placeholder: "support@yourcompany.com",
      required: false,
    },
    {
      key: "inbound_domain",
      label: "Inbound Domain",
      type: "text",
      placeholder: "yourcompany.com",
      required: false,
    },
    {
      key: "topic_arn",
      label: "SNS Topic ARN",
      type: "text",
      placeholder: "arn:aws:sns:us-east-1:123456789012:topic",
      required: false,
    },
    {
      key: "receipt_rule_set",
      label: "Receipt Rule Set",
      type: "text",
      placeholder: "default-rule-set",
      required: false,
    },
    {
      key: "receipt_rule_name",
      label: "Receipt Rule Name",
      type: "text",
      placeholder: "operious-inbound",
      required: false,
    },
    {
      key: "role_arn",
      label: "BYO Role ARN",
      type: "text",
      placeholder: "arn:aws:iam::123456789012:role/operious-ses",
      required: false,
    },
    {
      key: "external_id",
      label: "External ID",
      type: "text",
      placeholder: "tenant-external-id",
      required: false,
    },
    {
      key: "access_key_id",
      label: "Access Key ID",
      type: "password",
      placeholder: "AKIA...",
      required: false,
    },
    {
      key: "secret_access_key",
      label: "Secret Access Key",
      type: "password",
      placeholder: "Leave blank to keep current value",
      required: false,
    },
    {
      key: "session_token",
      label: "Session Token",
      type: "password",
      placeholder: "Temporary credentials only",
      required: false,
    },
  ],
  whatsapp: [
    {
      key: "waba_id",
      label: "WABA ID",
      type: "text",
      placeholder: "1234567890",
      required: false,
    },
    {
      key: "phone_number_id",
      label: "Phone Number ID",
      type: "text",
      placeholder: "1234567890",
      required: true,
      helpText: "Found in Meta Business Suite > WhatsApp > API Setup",
    },
    {
      key: "business_account_id",
      label: "Business Account ID",
      type: "text",
      placeholder: "1234567890",
      required: false,
    },
    {
      key: "graph_api_version",
      label: "Graph API Version",
      type: "text",
      placeholder: "v25.0",
      required: true,
    },
    {
      key: "app_id",
      label: "Meta App ID",
      type: "text",
      placeholder: "1234567890",
      required: false,
    },
    {
      key: "config_id",
      label: "Embedded Signup Config ID",
      type: "text",
      placeholder: "config-id",
      required: false,
    },
    {
      key: "access_token",
      label: "Access Token",
      type: "password",
      placeholder: "EAAxxxxxxxx",
      required: true,
    },
    {
      key: "webhook_verify_token",
      label: "Webhook Verify Token",
      type: "password",
      placeholder: "Generated if blank on first setup",
      required: false,
      helpText: "Set the generated or tenant-provided token in Meta webhooks",
    },
    {
      key: "app_secret",
      label: "Meta App Secret",
      type: "password",
      placeholder: "Optional signature validation secret",
      required: false,
    },
  ],
  voice: [
    {
      key: "account_sid",
      label: "Twilio Account SID",
      type: "text",
      placeholder: "ACxxxxxxxxxxxxxxxx",
      required: true,
    },
    {
      key: "auth_token",
      label: "Twilio Auth Token",
      type: "password",
      placeholder: "••••••••••••••••",
      required: true,
    },
    {
      key: "phone_number",
      label: "Twilio Phone Number",
      type: "text",
      placeholder: "+15551234567",
      required: true,
    },
  ],
  zendesk: [
    {
      key: "subdomain",
      label: "Zendesk Subdomain",
      type: "text",
      placeholder: "yourcompany",
      required: true,
      helpText: "yourcompany.zendesk.com - enter only 'yourcompany'",
    },
    {
      key: "email",
      label: "Agent Email",
      type: "text",
      placeholder: "agent@yourcompany.com",
      required: true,
    },
    {
      key: "api_token",
      label: "API Token",
      type: "password",
      placeholder: "••••••••••••••••",
      required: true,
    },
  ],
  jira: [
    {
      key: "base_url",
      label: "Jira Base URL",
      type: "text",
      placeholder: "https://yourcompany.atlassian.net",
      required: true,
    },
    {
      key: "email",
      label: "Account Email",
      type: "text",
      placeholder: "admin@yourcompany.com",
      required: true,
    },
    {
      key: "api_token",
      label: "API Token",
      type: "password",
      placeholder: "••••••••••••••••",
      required: true,
      helpText: "Generate at id.atlassian.com/manage-profile/security/api-tokens",
    },
    {
      key: "project_key",
      label: "Default Project Key",
      type: "text",
      placeholder: "OPS",
      required: false,
    },
  ],
  linear: [
    {
      key: "api_key",
      label: "Linear API Key",
      type: "password",
      placeholder: "lin_api_xxxxxxxxxxxx",
      required: true,
      helpText: "Generate at linear.app/settings/api",
    },
    {
      key: "team_id",
      label: "Team ID",
      type: "text",
      placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      required: false,
      helpText: "Found in Linear team settings URL",
    },
  ],
  shopify: [
    {
      key: "shop_domain",
      label: "Shop Domain",
      type: "text",
      placeholder: "yourstore.myshopify.com",
      required: true,
    },
    {
      key: "access_token",
      label: "Admin API Access Token",
      type: "password",
      placeholder: "shpat_xxxxxxxxxxxx",
      required: true,
      helpText: "Custom app access token from Shopify Partners",
    },
  ],
  shulex: [
    {
      key: "api_key",
      label: "Shulex API Key",
      type: "password",
      placeholder: "••••••••••••••••",
      required: true,
    },
    {
      key: "store_id",
      label: "Store ID",
      type: "text",
      placeholder: "your-store-id",
      required: true,
    },
  ],
  lark: [
    {
      key: "app_id",
      label: "Lark App ID",
      type: "text",
      placeholder: "cli_xxxxxxxxxxxx",
      required: true,
    },
    {
      key: "app_secret",
      label: "App Secret",
      type: "password",
      placeholder: "••••••••••••••••",
      required: true,
    },
  ],
};

const GENERIC_CREDENTIAL_FIELDS: ChannelCredentialField[] = [
  {
    key: "credentials",
    label: "Credentials (JSON)",
    type: "text",
    placeholder: '{"key": "value"}',
    required: false,
  },
];

export function GovernancePoliciesView({
  headerAddon = null,
}: {
  headerAddon?: React.ReactNode;
}) {
  const [modal, setModal] = useState<PolicyModal>({ type: "none" });
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => listGovernancePolicies(), []);
  const { data, error, isLoading, reload } = useApiResource(load);

  const closeModal = () => {
    setModal({ type: "none" });
    setFormError(null);
    setIsSubmitting(false);
  };

  // Every governance policy_type (resolution_autonomy, action_tools,
  // warranty_refund_rules, resolution_taxonomy, and any future type) shapes
  // autonomy, auto-send, or money/goods eligibility. The backend rejects
  // direct apply for all of them, so this form proposes a change request
  // (dual control: a different principal must approve it) rather than
  // writing the policy directly -- consistent with how ActionPolicyView
  // already proposes action_tools changes.
  const submitPolicy = async (
    event: React.FormEvent<HTMLFormElement>,
    policy?: TenantGovernancePolicy
  ) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError(null);
    const form = new FormData(event.currentTarget);
    try {
      const parameters = parseJsonObject(String(form.get("parameters") || "{}"));
      const status = String(form.get("status") || "draft");
      const effectiveFrom = new Date(String(form.get("effective_from") || "")).toISOString();
      const body = buildGovernancePolicyChangePayload({
        policyType: policy ? policy.policy_type : String(form.get("policy_type") || ""),
        parameters,
        status,
        effectiveFrom,
        policyId: policy?.policy_id,
      });
      await proposeConfigChangeRequest(body);
      closeModal();
      setNotice(
        "Policy change proposed. It now awaits approval by a different principal in Pending Approvals."
      );
      reload();
    } catch (caught: unknown) {
      setFormError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <ViewHeader
        eyebrow="GOVERNANCE · POLICIES"
        title="Governance Policies"
        actionLabel="Propose policy change"
        onAction={() => setModal({ type: "create" })}
      />
      {headerAddon}
      <GovernedNotice />
      {notice && <ProposedNotice message={notice} onDismiss={() => setNotice(null)} />}
      {isLoading && <LoadingState />}
      {error && !isLoading && (
        <ErrorState title="Governance policies unavailable" message={error} onAction={reload} />
      )}
      {data && !isLoading && !error && data.items.length === 0 && (
        <EmptyState
          title="No governance policies configured"
          message="The tenant policy endpoint returned no records for the current tenant."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}
      {data && !isLoading && !error && data.items.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {data.items.map((policy) => (
            <RecordCard
              key={policy.policy_id}
              title={policy.policy_type}
              meta={`v${policy.version} · ${policy.status}`}
              fields={[
                ["Policy ID", policy.policy_id],
                ["Approved by", policy.approved_by],
                ["Effective from", formatDateTime(policy.effective_from)],
                ["Parameters", stringify(policy.parameters)],
              ]}
              actions={
                <button
                  onClick={() => setModal({ type: "edit", policy })}
                  className="h-9 rounded border border-border-subtle px-3 text-[12px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
                >
                  Propose update
                </button>
              }
            />
          ))}
        </div>
      )}
      {modal.type !== "none" && (
        <Modal onClose={closeModal}>
          <PolicyForm
            policy={modal.type === "edit" ? modal.policy : undefined}
            error={formError}
            isSubmitting={isSubmitting}
            onSubmit={(event) =>
              void submitPolicy(event, modal.type === "edit" ? modal.policy : undefined)
            }
          />
        </Modal>
      )}
    </main>
  );
}

export function TopologyView() {
  const load = useCallback(() => listTopologyConfigurations(), []);
  return (
    <RecordListView
      eyebrow="PLATFORM · WORKFORCE MAP"
      title="Workforce Map"
      load={load}
      emptyTitle="No workforce map configured"
      emptyMessage="No agent organization has been configured for this tenant yet."
      renderItem={(topology: TenantTopologyConfiguration) => (
        <RecordCard
          title={topology.topology_name}
          meta={`v${topology.version} · ${topology.status}`}
          fields={[
            ["Config ID", topology.config_id],
            ["Configured by", topology.configured_by],
            ["Updated", formatDateTime(topology.updated_at)],
            ["Topology", stringify(topology.topology)],
          ]}
        />
      )}
    />
  );
}

export function ChannelsView() {
  const [modal, setModal] = useState<ChannelModal>({ type: "none" });
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const load = useCallback(() => listChannelConfigurations(), []);
  const { data, error, isLoading, reload } = useApiResource(load);

  const closeModal = () => {
    setModal({ type: "none" });
    setFormError(null);
    setIsSubmitting(false);
  };

  const submitChannel = async (
    event: React.FormEvent<HTMLFormElement>,
    channel?: TenantChannelConfiguration
  ) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError(null);
    const form = new FormData(event.currentTarget);
    try {
      const credentialsText = String(form.get("credentials") || "").trim();
      const webhookSecret = String(form.get("webhook_secret") || "").trim();
      const channelType = String(form.get("channel_type") || channel?.channel_type || "");
      const routingAddress = String(form.get("routing_address") || "");
      const status = String(form.get("status") || "pending_validation") as TenantChannelConfiguration["status"];
      const credentials = parseJsonObject(credentialsText || "{}");
      if (channelType === "whatsapp") {
        const request = buildWhatsAppSelfServiceRequest(credentials, status);
        if (channel) {
          await updateWhatsAppSelfServiceChannel(request);
        } else {
          await createWhatsAppSelfServiceChannel(request);
        }
      } else if (channelType === "email") {
        const request = buildSesSelfServiceRequest(
          credentials,
          routingAddress,
          status
        );
        if (channel) {
          await updateSesSelfServiceChannel(request);
        } else {
          await createSesSelfServiceChannel(request);
        }
      } else if (channel) {
        await updateChannelConfiguration(channel.config_id, {
          routing_address: routingAddress,
          credentials: credentialsText ? credentials : undefined,
          webhook_secret: webhookSecret || undefined,
          status,
        });
      } else {
        await createChannelConfiguration({
          channel_type: channelType,
          routing_address: routingAddress,
          credentials,
          webhook_secret: webhookSecret,
          status,
        });
      }
      closeModal();
      reload();
    } catch (caught: unknown) {
      setFormError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <ViewHeader
        eyebrow="BOUNDARY · CHANNELS"
        title="Channels"
        actionLabel="New Channel"
        onAction={() => setModal({ type: "create" })}
      />
      {isLoading && <LoadingState />}
      {error && !isLoading && (
        <ErrorState title="Channels unavailable" message={error} onAction={reload} />
      )}
      {data && !isLoading && !error && data.items.length === 0 && (
        <EmptyState
          title="No channels configured"
          message="The tenant channel endpoint returned no configured ingress or response channels."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}
      {data && !isLoading && !error && data.items.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {data.items.map((channel) => (
            <RecordCard
              key={channel.config_id}
              title={channel.channel_type}
              meta={channel.status}
              fields={[
                ["Config ID", channel.config_id],
                ["Routing address", channel.routing_address],
                ["Verified", channel.verified_at ? formatDateTime(channel.verified_at) : "Not verified"],
                [
                  "Validation error",
                  channel.last_validation_error ?? "No validation error recorded",
                ],
                [
                  "Self-service config",
                  stringify(channel.self_service_config),
                ],
                [
                  "Credential rotation",
                  channel.credential_rotated_at
                    ? formatDateTime(channel.credential_rotated_at)
                    : "No rotation recorded",
                ],
              ]}
              actions={
                <div className="flex gap-2">
                  <button
                    onClick={() => setModal({ type: "edit", channel })}
                    className="h-9 rounded border border-border-subtle px-3 text-[12px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
                  >
                    Edit
                  </button>
                </div>
              }
            />
          ))}
        </div>
      )}
      {modal.type !== "none" && (
        <Modal onClose={closeModal}>
          <ChannelForm
            channel={modal.type === "edit" ? modal.channel : undefined}
            error={formError}
            isSubmitting={isSubmitting}
            onSubmit={(event) =>
              void submitChannel(event, modal.type === "edit" ? modal.channel : undefined)
            }
          />
        </Modal>
      )}
    </main>
  );
}

export function AuditExportsView() {
  const load = useCallback(async () => {
    const now = new Date();
    const windowStart = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    const [alerts, deadLetters] = await Promise.all([
      listOperationalAlerts(windowStart, now),
      listDeadLetterExecutions(),
    ]);
    return {
      items: [
        ...alerts.items.map((item) => ({ kind: "alert" as const, item })),
        ...deadLetters.items.map((item) => ({ kind: "dead-letter" as const, item })),
      ],
      total: alerts.total + deadLetters.total,
      offset: 0,
    };
  }, []);

  return (
    <RecordListView
      eyebrow="AUDIT · EXPORTS"
      title="Audit & Exports"
      load={load}
      emptyTitle="No audit exceptions returned"
      emptyMessage="The observability alert and dead-letter endpoints returned no records for the current window."
      renderItem={(entry: { kind: "alert"; item: OperationalAlert } | { kind: "dead-letter"; item: DeadLetterExecution }) =>
        entry.kind === "alert" ? (
          <RecordCard
            title={entry.item.metric_name}
            meta={`${entry.item.severity} · ${entry.item.triggered ? "triggered" : "clear"}`}
            fields={[
              ["Alert ID", entry.item.alert_id],
              ["Observed", String(entry.item.observed_value)],
              ["Threshold", `${entry.item.threshold_operator} ${entry.item.threshold_value}`],
              ["Window", `${formatDateTime(entry.item.window_start)} to ${formatDateTime(entry.item.window_end)}`],
            ]}
          />
        ) : (
          <RecordCard
            title={entry.item.kind}
            meta={`DLQ · ${entry.item.state}`}
            fields={[
              ["Execution ID", entry.item.execution_id],
              ["Session ID", entry.item.session_id],
              ["Attempts", String(entry.item.attempt_count)],
              ["Error", entry.item.error ?? "No error message recorded"],
            ]}
          />
        )
      }
    />
  );
}

export function TeamRolesView() {
  return (
    <main className="min-w-0 flex-1 bg-canvas p-4 sm:p-6 lg:p-8">
      <PendingIntegrationState
        title="Team directory pending integration"
        message="No user or role-management endpoint exists in the current backend router set. The command center will render tenant team data here once an identity administration endpoint is available."
      />
    </main>
  );
}

export function SettingsView({ authSession }: { authSession: AuthSessionState }) {
  const principal = authSession.principal;
  const rows = [
    ["API base URL", getApiBaseUrl()],
    ["Tenant scope", principal?.tenant_id ?? getConfiguredTenantId() ?? "Not configured"],
    ["Principal scope", principal?.principal_id ?? getConfiguredPrincipalId() ?? "Not configured"],
    ["Operator label", authSession.operatorLabel || getConfiguredOperatorLabel()],
    ["Authority source", principal?.authority_source ?? "Not verified"],
    ["Capabilities", principal?.capabilities.join(", ") || "No capabilities returned"],
  ] as const;

  return (
    <main className="min-w-0 flex-1 bg-canvas p-4 sm:p-6 lg:p-8">
      <div className="max-w-5xl">
        <div className="eyebrow text-ink-tertiary mb-2">SETTINGS · RUNTIME</div>
        <h1 className="font-display text-[32px] font-semibold text-ink-primary mb-6">
          Settings
        </h1>
        <div className="overflow-hidden rounded-lg border border-border-subtle bg-surface">
          <div className="overflow-x-auto">
            <div className="min-w-[680px]">
              <div className="grid h-11 grid-cols-[220px_minmax(0,1fr)] items-center border-b border-border-subtle bg-surface-raised px-4 sm:h-9">
                <DenseHeader>Tenant Runtime Field</DenseHeader>
                <DenseHeader>Resolved Value</DenseHeader>
              </div>
              {rows.map(([label, value], index) => (
                <SettingRow
                  key={label}
                  label={label}
                  value={value}
                  isOdd={index % 2 === 1}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-lg border border-border-subtle bg-surface p-4">
          <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
            Signed Session
          </div>
          {authSession.error && (
            <div className="mb-3 rounded border border-warning-amber/30 bg-warning-amber/10 px-3 py-2 text-[13px] text-warning-amber">
              {authSession.error}
            </div>
          )}
          <div className="flex justify-end">
            <button
              onClick={authSession.reload}
              className="h-11 rounded border border-border-subtle px-4 text-[13px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
            >
              Refresh
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

function RecordListView<T>({
  eyebrow,
  title,
  load,
  emptyTitle,
  emptyMessage,
  headerAction,
  renderItem,
}: RecordListProps<T>) {
  const { data, error, isLoading, reload } = useApiResource(load);

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <ViewHeader eyebrow={eyebrow} title={title} headerAction={headerAction} />
      {isLoading && <LoadingState />}
      {error && !isLoading && (
        <ErrorState title={`${title} unavailable`} message={error} onAction={reload} />
      )}
      {data && !isLoading && !error && data.items.length === 0 && (
        <EmptyState title={emptyTitle} message={emptyMessage} onAction={reload} actionLabel="Refresh" />
      )}
      {data && !isLoading && !error && data.items.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {data.items.map((item, index) => (
            <div key={index}>{renderItem(item)}</div>
          ))}
        </div>
      )}
    </main>
  );
}

function ViewHeader({
  eyebrow,
  title,
  actionLabel,
  onAction,
  headerAction,
}: {
  eyebrow: string;
  title: string;
  actionLabel?: string;
  onAction?: () => void;
  headerAction?: React.ReactNode;
}) {
  return (
    <>
      <div className="eyebrow text-ink-tertiary mb-2">{eyebrow}</div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="font-display text-[32px] font-semibold text-ink-primary">
          {title}
        </h1>
        {headerAction}
        {actionLabel && onAction && (
          <button
            onClick={onAction}
            className="h-11 rounded border border-border-subtle bg-surface px-4 text-[13px] text-ink-secondary hover:border-border-defined hover:text-ink-primary sm:h-10"
          >
            {actionLabel}
          </button>
        )}
      </div>
    </>
  );
}

function RecordCard({
  title,
  meta,
  fields,
  actions,
}: {
  title: string;
  meta: string;
  fields: [string, string][];
  actions?: React.ReactNode;
}) {
  return (
    <article className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="truncate text-[18px] font-semibold text-ink-primary">
            {title}
          </h2>
          {actions && <div className="mt-3">{actions}</div>}
        </div>
        <span className="shrink-0 rounded border border-border-subtle px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
          {meta}
        </span>
      </div>
      <div className="mt-4 grid gap-2">
        {fields.map(([label, value]) => (
          <div key={label}>
            <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
              {label}
            </div>
            <div className="mt-1 break-words text-[13px] leading-relaxed text-ink-secondary">
              {value}
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}

function Modal({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 sm:p-6">
      <div className="max-h-[88dvh] w-full max-w-3xl overflow-y-auto rounded-lg border border-border-subtle bg-surface p-4 shadow-elevated sm:p-6">
        <div className="mb-4 flex justify-end">
          <button
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle text-ink-tertiary hover:text-ink-primary"
            aria-label="Close modal"
          >
            X
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function PolicyForm({
  policy,
  error,
  isSubmitting,
  onSubmit,
}: {
  policy?: TenantGovernancePolicy;
  error: string | null;
  isSubmitting: boolean;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h2 className="font-display text-[24px] font-semibold text-ink-primary">
        {policy ? "Propose Policy Update" : "Propose New Policy"}
      </h2>
      {error && <FormError message={error} />}
      <TextInput name="policy_type" label="Policy type" defaultValue={policy?.policy_type ?? ""} disabled={Boolean(policy)} required />
      <SelectInput
        name="status"
        label="Status"
        defaultValue={policy?.status ?? "draft"}
        options={["draft", "active", "archived"]}
      />
      <TextInput
        name="effective_from"
        label="Effective from"
        type="datetime-local"
        defaultValue={toDateTimeLocal(policy?.effective_from)}
        required
      />
      <JsonInput
        name="parameters"
        label="Parameters"
        defaultValue={JSON.stringify(policy?.parameters ?? {}, null, 2)}
      />
      <SubmitButton isSubmitting={isSubmitting} label={policy ? "Propose update" : "Propose policy"} />
    </form>
  );
}

function ChannelForm({
  channel,
  error,
  isSubmitting,
  onSubmit,
}: {
  channel?: TenantChannelConfiguration;
  error: string | null;
  isSubmitting: boolean;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}) {
  const [channelType, setChannelType] = useState(channel?.channel_type ?? "email");
  const [credentialValues, setCredentialValues] = useState<Record<string, string>>({});
  const credentialFields =
    CHANNEL_CREDENTIAL_FIELDS[channelType] ?? GENERIC_CREDENTIAL_FIELDS;
  const usesGenericCredentials = credentialFields === GENERIC_CREDENTIAL_FIELDS;
  const hasCredentialInput = Object.values(credentialValues).some(
    (value) => value.trim() !== ""
  );
  const requiresCredentialSet = !channel || hasCredentialInput;
  const credentialPayload = buildCredentialPayload(
    credentialFields,
    credentialValues
  );
  const credentialJson = requiresCredentialSet
    ? JSON.stringify(credentialPayload)
    : "";
  const channelTypeOptions = CHANNEL_TYPE_OPTIONS.includes(channelType)
    ? CHANNEL_TYPE_OPTIONS
    : [channelType, ...CHANNEL_TYPE_OPTIONS];

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h2 className="font-display text-[24px] font-semibold text-ink-primary">
        {channel ? "Edit Channel" : "New Channel"}
      </h2>
      {error && <FormError message={error} />}
      <label className="block">
        <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
          Channel type
        </span>
        <select
          name="channel_type"
          value={channelType}
          disabled={Boolean(channel)}
          onChange={(event) => {
            setChannelType(event.target.value);
            setCredentialValues({});
          }}
          className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary disabled:opacity-60 sm:h-10"
        >
          {channelTypeOptions.map((option) => (
            <option key={option} value={option}>
              {CHANNEL_TYPE_LABELS[option] ?? formatLabel(option)}
            </option>
          ))}
        </select>
      </label>
      <TextInput name="routing_address" label="Routing address" defaultValue={channel?.routing_address ?? ""} required />
      <SelectInput
        name="status"
        label="Status"
        defaultValue={channel?.status ?? "pending_validation"}
        options={["draft", "pending_validation", "validation_failed", "disabled"]}
      />
      {channel && (
        <div className="rounded border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-secondary">
          Credentials are set. Enter new values to rotate.
        </div>
      )}
      {usesGenericCredentials ? (
        <label className="block">
          <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
            {GENERIC_CREDENTIAL_FIELDS[0].label}
          </span>
          <textarea
            name="credentials"
            defaultValue={channel ? "" : "{}"}
            placeholder={GENERIC_CREDENTIAL_FIELDS[0].placeholder}
            rows={8}
            required={!channel}
            className="w-full rounded border border-border-subtle bg-surface-raised px-3 py-2 font-mono text-[12px] leading-relaxed text-ink-primary focus:outline-none focus:border-gold-primary"
          />
        </label>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <input type="hidden" name="credentials" value={credentialJson} />
          {credentialFields.map((field) => (
            <CredentialInput
              key={field.key}
              field={field}
              value={credentialValues[field.key] ?? ""}
              isEditMode={Boolean(channel)}
              required={field.required && requiresCredentialSet}
              onChange={(value) =>
                setCredentialValues((previous) => ({
                  ...previous,
                  [field.key]: value,
                }))
              }
            />
          ))}
        </div>
      )}
      <TextInput name="webhook_secret" label="Webhook secret" type="password" required={!channel} />
      <SubmitButton isSubmitting={isSubmitting} label={channel ? "Save channel" : "Create channel"} />
    </form>
  );
}

function CredentialInput({
  field,
  value,
  isEditMode,
  required,
  onChange,
}: {
  field: ChannelCredentialField;
  value: string;
  isEditMode: boolean;
  required: boolean;
  onChange: (value: string) => void;
}) {
  const placeholder =
    isEditMode && field.type === "password"
      ? "Leave blank to keep current value"
      : field.placeholder;

  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {field.label}
        {required && <span className="ml-1 text-red-alert">*</span>}
      </span>
      {field.type === "select" ? (
        <select
          value={value || field.options?.[0] || ""}
          onChange={(event) => onChange(event.target.value)}
          required={required}
          className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
        >
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {formatLabel(option)}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.type}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          required={required}
          autoComplete={field.type === "password" ? "new-password" : "off"}
          className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
        />
      )}
      {field.helpText && (
        <span className="mt-1 block text-[12px] leading-relaxed text-ink-tertiary">
          {field.helpText}
        </span>
      )}
    </label>
  );
}

function buildCredentialPayload(
  fields: ChannelCredentialField[],
  credentialValues: Record<string, string>
): Record<string, string> {
  const payload: Record<string, string> = {};
  for (const field of fields) {
    const value =
      credentialValues[field.key]?.trim()
      || (field.type === "select" ? field.options?.[0] : undefined);
    if (value) {
      payload[field.key] = value;
    }
  }
  return payload;
}

function buildWhatsAppSelfServiceRequest(
  credentials: Record<string, unknown>,
  status: TenantChannelConfiguration["status"]
): TenantWhatsAppSelfServiceRequest {
  return compactObject({
    waba_id: optionalText(credentials.waba_id),
    phone_number_id: requiredText(credentials.phone_number_id, "phone_number_id"),
    business_account_id: optionalText(credentials.business_account_id),
    graph_api_version: optionalText(credentials.graph_api_version) ?? "v25.0",
    app_id: optionalText(credentials.app_id),
    config_id: optionalText(credentials.config_id),
    access_token: optionalText(credentials.access_token),
    system_user_token: optionalText(credentials.system_user_token),
    webhook_verify_token: optionalText(credentials.webhook_verify_token),
    app_secret: optionalText(credentials.app_secret),
    status,
  });
}

function buildSesSelfServiceRequest(
  credentials: Record<string, unknown>,
  routingAddress: string,
  status: TenantChannelConfiguration["status"]
): TenantSesSelfServiceRequest {
  const route = routingAddress.trim();
  const sourceEmail = optionalText(credentials.source_email);
  const sourceDomain = optionalText(credentials.source_domain);
  const fallbackRoute =
    sourceEmail || sourceDomain || (route.includes("@") ? route : undefined);
  const fallbackDomain =
    sourceDomain || (!route.includes("@") && route ? route : undefined);
  return compactObject({
    mode: sesMode(optionalText(credentials.mode)),
    region: requiredText(credentials.region, "region"),
    source_email: sourceEmail ?? fallbackRoute,
    source_domain: sourceDomain ?? fallbackDomain,
    inbound_address: optionalText(credentials.inbound_address),
    inbound_domain: optionalText(credentials.inbound_domain),
    topic_arn: optionalText(credentials.topic_arn),
    receipt_rule_set: optionalText(credentials.receipt_rule_set),
    receipt_rule_name: optionalText(credentials.receipt_rule_name),
    role_arn: optionalText(credentials.role_arn),
    external_id: optionalText(credentials.external_id),
    access_key_id: optionalText(credentials.access_key_id),
    secret_access_key: optionalText(credentials.secret_access_key),
    session_token: optionalText(credentials.session_token),
    status,
  });
}

function compactObject<T extends Record<string, unknown>>(value: T): T {
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (item !== undefined && item !== null && item !== "") {
      out[key] = item;
    }
  }
  return out as T;
}

function optionalText(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const text = value.trim();
  return text || undefined;
}

function requiredText(value: unknown, key: string): string {
  const text = optionalText(value);
  if (!text) throw new Error(`${key} is required`);
  return text;
}

function sesMode(value: string | undefined): TenantSesSelfServiceRequest["mode"] {
  if (value === "managed" || value === "byo_role" || value === "byo_access_key") {
    return value;
  }
  return "managed";
}

function TextInput({
  label,
  name,
  type = "text",
  defaultValue = "",
  disabled = false,
  required = false,
}: {
  label: string;
  name: string;
  type?: string;
  defaultValue?: string;
  disabled?: boolean;
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
        defaultValue={defaultValue}
        disabled={disabled}
        required={required}
        className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary disabled:opacity-60 sm:h-10"
      />
    </label>
  );
}

function SelectInput({
  label,
  name,
  defaultValue,
  options,
  disabled = false,
}: {
  label: string;
  name: string;
  defaultValue: string;
  options: string[];
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <select
        name={name}
        defaultValue={defaultValue}
        disabled={disabled}
        className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary disabled:opacity-60 sm:h-10"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {formatLabel(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function JsonInput({
  label,
  name,
  defaultValue,
  required = true,
}: {
  label: string;
  name: string;
  defaultValue: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <textarea
        name={name}
        defaultValue={defaultValue}
        rows={8}
        required={required}
        className="w-full rounded border border-border-subtle bg-surface-raised px-3 py-2 font-mono text-[12px] leading-relaxed text-ink-primary focus:outline-none focus:border-gold-primary"
      />
    </label>
  );
}

function SubmitButton({ isSubmitting, label }: { isSubmitting: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={isSubmitting}
      className="inline-flex min-h-11 items-center justify-center rounded bg-gold-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-gold-muted disabled:opacity-60"
    >
      {isSubmitting ? "Submitting..." : label}
    </button>
  );
}

function FormError({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
      {message}
    </div>
  );
}

function DenseHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
      {children}
    </div>
  );
}

function SettingRow({
  label,
  value,
  isOdd,
}: {
  label: string;
  value: string;
  isOdd: boolean;
}) {
  return (
    <div className={`grid min-h-11 grid-cols-[220px_minmax(0,1fr)] items-center border-b border-border-subtle px-4 last:border-b-0 sm:min-h-10 ${isOdd ? "bg-canvas/50" : "bg-surface"}`}>
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </div>
      <div className="break-words font-mono text-[12px] text-ink-primary">{value}</div>
    </div>
  );
}

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Expected a JSON object");
  }
  return parsed as Record<string, unknown>;
}

function stringify(value: Record<string, unknown>): string {
  if (Object.keys(value).length === 0) return "No parameters recorded";
  return JSON.stringify(value);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function toDateTimeLocal(value?: string): string {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 16);
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
