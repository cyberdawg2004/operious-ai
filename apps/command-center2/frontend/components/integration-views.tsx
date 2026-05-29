"use client";

import { useCallback, useState } from "react";
import {
  createChannelConfiguration,
  createGovernancePolicy,
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
  updateChannelConfiguration,
  updateGovernancePolicy,
  verifyChannelConfiguration,
  type ApiPage,
  type DeadLetterExecution,
  type OperationalAlert,
  type TenantChannelConfiguration,
  type TenantGovernancePolicy,
  type TenantTopologyConfiguration,
} from "@/lib/api";
import type { AuthSessionState } from "@/lib/use-auth-session";
import { useApiResource } from "@/lib/use-api-resource";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PendingIntegrationState,
} from "@/components/data-state";

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

export function GovernancePoliciesView({
  headerAddon = null,
}: {
  headerAddon?: React.ReactNode;
}) {
  const [modal, setModal] = useState<PolicyModal>({ type: "none" });
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const load = useCallback(() => listGovernancePolicies(), []);
  const { data, error, isLoading, reload } = useApiResource(load);

  const closeModal = () => {
    setModal({ type: "none" });
    setFormError(null);
    setIsSubmitting(false);
  };

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
      const status = String(form.get("status") || "draft") as TenantGovernancePolicy["status"];
      const effectiveFrom = new Date(String(form.get("effective_from") || "")).toISOString();
      if (policy) {
        await updateGovernancePolicy(policy.policy_id, {
          parameters,
          status,
          effective_from: effectiveFrom,
        });
      } else {
        await createGovernancePolicy({
          policy_type: String(form.get("policy_type") || ""),
          parameters,
          status,
          effective_from: effectiveFrom,
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
        eyebrow="GOVERNANCE · POLICIES"
        title="Governance Policies"
        actionLabel="New Policy"
        onAction={() => setModal({ type: "create" })}
      />
      {headerAddon}
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
                  Edit
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
      eyebrow="TOPOLOGY · CONFIGURATION"
      title="Topology"
      load={load}
      emptyTitle="No topology configurations"
      emptyMessage="The tenant topology endpoint returned no configured agent topology records."
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
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyChannelId, setBusyChannelId] = useState<string | null>(null);
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
      const status = String(form.get("status") || "pending_verification") as TenantChannelConfiguration["status"];
      if (channel) {
        await updateChannelConfiguration(channel.config_id, {
          routing_address: String(form.get("routing_address") || ""),
          credentials: credentialsText ? parseJsonObject(credentialsText) : undefined,
          webhook_secret: webhookSecret || undefined,
          status,
        });
      } else {
        await createChannelConfiguration({
          channel_type: String(form.get("channel_type") || ""),
          routing_address: String(form.get("routing_address") || ""),
          credentials: parseJsonObject(credentialsText || "{}"),
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

  const verifyChannel = async (channel: TenantChannelConfiguration) => {
    setBusyChannelId(channel.config_id);
    setActionError(null);
    try {
      await verifyChannelConfiguration(channel.config_id);
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusyChannelId(null);
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
      {actionError && !isLoading && (
        <div className="mb-5">
          <ErrorState title="Channel action failed" message={actionError} actionLabel="Dismiss" onAction={() => setActionError(null)} />
        </div>
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
                  <button
                    onClick={() => void verifyChannel(channel)}
                    disabled={busyChannelId === channel.config_id}
                    className="h-9 rounded border border-gold-primary/40 px-3 text-[12px] text-gold-primary hover:bg-gold-primary/10 disabled:opacity-50"
                  >
                    Verify
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
  const [token, setToken] = useState(() =>
    typeof window === "undefined"
      ? ""
      : window.localStorage.getItem("operious_access_token") ?? ""
  );
  const principal = authSession.principal;
  const rows = [
    ["API base URL", getApiBaseUrl()],
    ["Tenant scope", principal?.tenant_id ?? getConfiguredTenantId() ?? "Not configured"],
    ["Principal scope", principal?.principal_id ?? getConfiguredPrincipalId() ?? "Not configured"],
    ["Operator label", authSession.operatorLabel || getConfiguredOperatorLabel()],
    ["Authority source", principal?.authority_source ?? "Not verified"],
    ["Capabilities", principal?.capabilities.join(", ") || "No capabilities returned"],
  ] as const;

  const saveToken = () => {
    window.localStorage.setItem("operious_access_token", token.trim());
    authSession.reload();
  };

  const clearToken = () => {
    window.localStorage.removeItem("operious_access_token");
    setToken("");
    authSession.reload();
  };

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
          <div className="flex flex-col gap-3 md:flex-row md:items-center">
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Bearer token"
              className="h-11 min-w-0 flex-1 rounded border border-border-subtle bg-surface-raised px-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none focus:border-gold-primary"
            />
            <button
              onClick={saveToken}
              className="h-11 rounded bg-ink-primary px-4 text-[13px] font-medium text-white hover:opacity-90"
            >
              Save
            </button>
            <button
              onClick={clearToken}
              className="h-11 rounded border border-border-subtle px-4 text-[13px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
            >
              Clear
            </button>
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
        {policy ? "Edit Policy" : "New Policy"}
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
      <SubmitButton isSubmitting={isSubmitting} label={policy ? "Save policy" : "Create policy"} />
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
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h2 className="font-display text-[24px] font-semibold text-ink-primary">
        {channel ? "Edit Channel" : "New Channel"}
      </h2>
      {error && <FormError message={error} />}
      <SelectInput
        name="channel_type"
        label="Channel type"
        defaultValue={channel?.channel_type ?? "email"}
        disabled={Boolean(channel)}
        options={["email", "whatsapp", "shulex", "lark", "zendesk", "voice"]}
      />
      <TextInput name="routing_address" label="Routing address" defaultValue={channel?.routing_address ?? ""} required />
      <SelectInput
        name="status"
        label="Status"
        defaultValue={channel?.status ?? "pending_verification"}
        options={["pending_verification", "active", "paused", "error"]}
      />
      <JsonInput
        name="credentials"
        label="Credentials JSON"
        defaultValue={channel ? "" : "{}"}
        required={!channel}
      />
      <TextInput name="webhook_secret" label="Webhook secret" type="password" required={!channel} />
      <SubmitButton isSubmitting={isSubmitting} label={channel ? "Save channel" : "Create channel"} />
    </form>
  );
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
