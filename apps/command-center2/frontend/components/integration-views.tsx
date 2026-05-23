"use client";

import { useCallback } from "react";
import {
  getApiBaseUrl,
  getConfiguredOperatorLabel,
  getConfiguredPrincipalId,
  getConfiguredTenantId,
  listChannelConfigurations,
  listDeadLetterExecutions,
  listGovernancePolicies,
  listOperationalAlerts,
  listTopologyConfigurations,
  type ApiPage,
  type DeadLetterExecution,
  type OperationalAlert,
  type TenantChannelConfiguration,
  type TenantGovernancePolicy,
  type TenantTopologyConfiguration,
} from "@/lib/api";
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
  renderItem: (item: T) => React.ReactNode;
};

export function GovernancePoliciesView() {
  const load = useCallback(() => listGovernancePolicies(), []);
  return (
    <RecordListView
      eyebrow="GOVERNANCE · POLICIES"
      title="Governance Policies"
      load={load}
      emptyTitle="No governance policies configured"
      emptyMessage="The tenant policy endpoint returned no records for the current tenant."
      renderItem={(policy: TenantGovernancePolicy) => (
        <RecordCard
          title={policy.policy_type}
          meta={`v${policy.version} · ${policy.status}`}
          fields={[
            ["Policy ID", policy.policy_id],
            ["Approved by", policy.approved_by],
            ["Effective from", formatDateTime(policy.effective_from)],
            ["Parameters", stringify(policy.parameters)],
          ]}
        />
      )}
    />
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
  const load = useCallback(() => listChannelConfigurations(), []);
  return (
    <RecordListView
      eyebrow="BOUNDARY · CHANNELS"
      title="Channels"
      load={load}
      emptyTitle="No channels configured"
      emptyMessage="The tenant channel endpoint returned no configured ingress or response channels."
      renderItem={(channel: TenantChannelConfiguration) => (
        <RecordCard
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
        />
      )}
    />
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

export function SettingsView() {
  const tenantId = getConfiguredTenantId();
  const principalId = getConfiguredPrincipalId();
  const rows = [
    ["API base URL", getApiBaseUrl()],
    ["Tenant scope", tenantId ?? "Not configured"],
    ["Principal scope", principalId ?? "Not configured"],
    ["Operator label", getConfiguredOperatorLabel()],
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
            <div className="min-w-[640px]">
              <div className="grid h-9 grid-cols-[220px_minmax(0,1fr)] items-center border-b border-border-subtle bg-surface-raised px-4">
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
  renderItem,
}: RecordListProps<T>) {
  const { data, error, isLoading, reload } = useApiResource(load);

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <div className="eyebrow text-ink-tertiary mb-2">{eyebrow}</div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="font-display text-[32px] font-semibold text-ink-primary">
          {title}
        </h1>
        <button
          onClick={reload}
          className="h-10 rounded border border-border-subtle bg-surface px-4 text-[13px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
        >
          Refresh
        </button>
      </div>

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

function RecordCard({
  title,
  meta,
  fields,
}: {
  title: string;
  meta: string;
  fields: [string, string][];
}) {
  return (
    <article className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-[18px] font-semibold text-ink-primary">
          {title}
        </h2>
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
    <div className={`grid min-h-10 grid-cols-[220px_minmax(0,1fr)] items-center border-b border-border-subtle px-4 last:border-b-0 ${isOdd ? "bg-canvas/50" : "bg-surface"}`}>
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </div>
      <div className="break-words font-mono text-[12px] text-ink-primary">{value}</div>
    </div>
  );
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
