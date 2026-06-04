"use client";

import { useCallback, useMemo, useState } from "react";
import {
  formatApiError,
  listConnectorConfigurations,
  listChannelConfigurations,
  listGovernancePolicies,
  proposeConfigChangeRequest,
  type ApiPage,
  type TenantChannelConfiguration,
  type TenantConnectorConfiguration,
  type TenantGovernancePolicy,
} from "@/lib/api";
import {
  ACTION_TOOLS_POLICY_TYPE,
  CONNECTOR_STATUS_OPTIONS,
  CONNECTOR_TYPE_OPTIONS,
  HTTP_METHOD_OPTIONS,
  POLICY_DECISION_VALUES,
  buildActionPolicyChangePayload,
  buildChannelCredentialChangePayload,
  buildConnectorChangePayload,
  type PolicyDecision,
} from "@/lib/config-change-payloads";
import { useApiResource } from "@/lib/use-api-resource";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";

/**
 * Per-connector-type credential field. Credentials NEVER ride the connector
 * config payload (Step 0 constraint A) — they are rotated here via the channel
 * credential path, write-only: blank means keep the current value, and the
 * current value is never read back or displayed.
 */
const CONNECTOR_CREDENTIAL_KEYS: Record<string, { key: string; label: string }[]> = {
  email: [{ key: "smtp_password", label: "SMTP Password" }],
  whatsapp: [{ key: "access_token", label: "Access Token" }],
  voice: [{ key: "auth_token", label: "Auth Token" }],
  zendesk: [{ key: "api_token", label: "API Token" }],
  jira: [{ key: "api_token", label: "API Token" }],
  linear: [{ key: "api_key", label: "API Key" }],
  shopify: [{ key: "access_token", label: "Admin API Access Token" }],
  shulex: [{ key: "api_key", label: "API Key" }],
  lark: [{ key: "app_secret", label: "App Secret" }],
};

const KEEP_CURRENT_PLACEHOLDER = "Leave blank to keep current value";

type ConnectorModal =
  | { type: "none" }
  | { type: "propose"; connector?: TenantConnectorConfiguration }
  | { type: "credential"; connector: TenantConnectorConfiguration };

// ─── Connector-config editor ──────────────────────────────────────────────

export function ConnectorConfigView() {
  const [modal, setModal] = useState<ConnectorModal>({ type: "none" });
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => listConnectorConfigurations({ status: "active" }), []);
  const { data, error, isLoading, reload } = useApiResource(load);

  const closeModal = () => setModal({ type: "none" });
  const onProposed = (message: string) => {
    setNotice(message);
    closeModal();
    reload();
  };

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <Header
        eyebrow="BOUNDARY · CONNECTORS"
        title="Connector Config"
        actionLabel="Propose new connector"
        onAction={() => setModal({ type: "propose" })}
      />
      <GovernedNotice />
      {notice && <ProposedNotice message={notice} onDismiss={() => setNotice(null)} />}
      {isLoading && <LoadingState />}
      {error && !isLoading && (
        <ErrorState title="Connector configs unavailable" message={error} onAction={reload} />
      )}
      {data && !isLoading && !error && data.items.length === 0 && (
        <EmptyState
          title="No active connector configs"
          message="The tenant connector endpoint returned no active connector configurations."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}
      {data && !isLoading && !error && data.items.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {data.items.map((connector) => (
            <ConnectorCard
              key={`${connector.tool_name}:${connector.version}`}
              connector={connector}
              onProposeChange={() => setModal({ type: "propose", connector })}
              onSetCredential={() => setModal({ type: "credential", connector })}
            />
          ))}
        </div>
      )}

      {modal.type === "propose" && (
        <Modal onClose={closeModal}>
          <ConnectorProposeForm
            connector={modal.connector}
            onProposed={() =>
              onProposed("Connector config change proposed — pending approval by another principal.")
            }
          />
        </Modal>
      )}
      {modal.type === "credential" && (
        <Modal onClose={closeModal}>
          <ConnectorCredentialForm
            connector={modal.connector}
            onProposed={() =>
              onProposed("Credential rotation proposed via the channel credential path — pending approval.")
            }
          />
        </Modal>
      )}
    </main>
  );
}

function ConnectorCard({
  connector,
  onProposeChange,
  onSetCredential,
}: {
  connector: TenantConnectorConfiguration;
  onProposeChange: () => void;
  onSetCredential: () => void;
}) {
  return (
    <article className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="truncate text-[18px] font-semibold text-ink-primary">
            {connector.tool_name}
          </h2>
          <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
            {connector.connector_type}
          </p>
        </div>
        <span className="shrink-0 rounded border border-border-subtle px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
          v{connector.version} · {connector.status}
        </span>
      </div>
      <div className="mt-4 grid gap-2">
        <Field label="Method" value={`${connector.http_method}`} />
        <Field label="Endpoint" value={connector.endpoint_template} />
        <Field label="Host" value={connector.endpoint_host} />
        <Field label="Idempotency header" value={connector.idempotency_header_name} />
        <Field label="Configured by" value={connector.configured_by} />
        <Field label="Content sha256" value={connector.content_sha256} />
        <Field
          label="Previous sha256"
          value={connector.previous_version_sha256 ?? "Genesis version"}
        />
      </div>
      <div className="mt-4 flex flex-col gap-2 border-t border-border-subtle pt-4 sm:flex-row">
        <div className="flex-1 rounded border border-border-subtle bg-surface-raised p-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
            Step 1 · Config
          </p>
          <button
            onClick={onProposeChange}
            className="mt-2 h-9 w-full rounded border border-border-subtle px-3 text-[12px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
          >
            Propose config change
          </button>
        </div>
        <div className="flex-1 rounded border border-border-subtle bg-surface-raised p-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
            Step 2 · Credential (separate path)
          </p>
          <button
            onClick={onSetCredential}
            className="mt-2 h-9 w-full rounded border border-gold-primary/40 px-3 text-[12px] text-gold-primary hover:bg-gold-primary/10"
          >
            Set credential
          </button>
        </div>
      </div>
    </article>
  );
}

function ConnectorProposeForm({
  connector,
  onProposed,
}: {
  connector?: TenantConnectorConfiguration;
  onProposed: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      const body = buildConnectorChangePayload({
        connector_type: String(form.get("connector_type") || ""),
        tool_name: String(form.get("tool_name") || ""),
        http_method: String(form.get("http_method") || "POST"),
        endpoint_template: String(form.get("endpoint_template") || ""),
        endpoint_host: String(form.get("endpoint_host") || ""),
        field_mappings: parseJsonObject(String(form.get("field_mappings") || "{}")),
        idempotency_header_name: String(form.get("idempotency_header_name") || ""),
        response_parse: parseJsonObject(String(form.get("response_parse") || "{}")),
        success_status_codes: parseStatusCodes(String(form.get("success_status_codes") || "")),
        status: String(form.get("status") || "active"),
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
        {connector ? "Propose Connector Change" : "Propose New Connector"}
      </h2>
      <p className="text-[13px] leading-relaxed text-ink-secondary">
        This proposes a governed config change. It is <strong>not</strong> applied
        until a different principal approves it. Credentials are set separately via
        the channel credential path — never here.
      </p>
      {error && <FormError message={error} />}
      <Select
        name="connector_type"
        label="Connector type"
        defaultValue={connector?.connector_type ?? CONNECTOR_TYPE_OPTIONS[0]}
        options={[...CONNECTOR_TYPE_OPTIONS]}
      />
      <Text name="tool_name" label="Tool name" defaultValue={connector?.tool_name ?? ""} required />
      <Select
        name="http_method"
        label="HTTP method"
        defaultValue={connector?.http_method ?? "POST"}
        options={[...HTTP_METHOD_OPTIONS]}
      />
      <Text
        name="endpoint_template"
        label="Endpoint template (HTTPS)"
        defaultValue={connector?.endpoint_template ?? ""}
        required
      />
      <Text
        name="endpoint_host"
        label="Endpoint host"
        defaultValue={connector?.endpoint_host ?? ""}
        required
      />
      <Text
        name="idempotency_header_name"
        label="Idempotency header name"
        defaultValue={connector?.idempotency_header_name ?? "Idempotency-Key"}
        required
      />
      <Text
        name="success_status_codes"
        label="Success status codes (comma separated)"
        defaultValue={(connector?.success_status_codes ?? [200]).join(", ")}
        required
      />
      <Select
        name="status"
        label="Status"
        defaultValue={connector?.status ?? "active"}
        options={[...CONNECTOR_STATUS_OPTIONS]}
      />
      <JsonArea
        name="field_mappings"
        label="Field mappings (JSON)"
        defaultValue={JSON.stringify(connector?.field_mappings ?? {}, null, 2)}
      />
      <JsonArea
        name="response_parse"
        label="Response parse (JSON)"
        defaultValue={JSON.stringify(connector?.response_parse ?? {}, null, 2)}
      />
      <Submit isSubmitting={isSubmitting} label="Propose config change" />
    </form>
  );
}

function ConnectorCredentialForm({
  connector,
  onProposed,
}: {
  connector: TenantConnectorConfiguration;
  onProposed: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const loadChannels = useCallback(() => listChannelConfigurations(), []);
  const { data: channelPage, isLoading } = useApiResource<ApiPage<TenantChannelConfiguration>>(
    loadChannels
  );
  const matchingChannels = useMemo(
    () =>
      (channelPage?.items ?? []).filter(
        (channel) => channel.channel_type === connector.connector_type
      ),
    [channelPage, connector.connector_type]
  );
  const credentialKeys = CONNECTOR_CREDENTIAL_KEYS[connector.connector_type] ?? [];

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const configId = String(form.get("config_id") || "");
    if (!configId) {
      setError("Select the channel whose credential to rotate.");
      setIsSubmitting(false);
      return;
    }
    const credentials: Record<string, string> = {};
    for (const field of credentialKeys) {
      credentials[field.key] = String(form.get(field.key) || "");
    }
    try {
      // Credential rotation is a CHANNEL change request — never a connector one.
      const body = buildChannelCredentialChangePayload({
        configId,
        credentials,
        webhookSecret: String(form.get("webhook_secret") || ""),
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
        Set Connector Credential
      </h2>
      <div className="rounded border border-gold-primary/40 bg-gold-bg p-3 text-[13px] leading-relaxed text-ink-primary">
        This is a <strong>separate step</strong> from the connector config. The
        credential is rotated through the channel credential path as its own
        governed change request. Existing values are never displayed — leave a
        field blank to keep its current value.
      </div>
      {error && <FormError message={error} />}
      {isLoading && <LoadingState label="Loading channels..." />}
      {!isLoading && matchingChannels.length === 0 && (
        <div className="rounded border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-secondary">
          No <strong>{connector.connector_type}</strong> channel is configured yet.
          Create the channel first, then rotate its credential here.
        </div>
      )}
      {matchingChannels.length > 0 && (
        <label className="block">
          <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
            Target channel
          </span>
          <select
            name="config_id"
            className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
          >
            {matchingChannels.map((channel) => (
              <option key={channel.config_id} value={channel.config_id}>
                {channel.routing_address} ({channel.config_id.slice(0, 8)})
              </option>
            ))}
          </select>
        </label>
      )}
      {credentialKeys.map((field) => (
        <WriteOnlyInput key={field.key} name={field.key} label={field.label} />
      ))}
      <WriteOnlyInput name="webhook_secret" label="Webhook secret" />
      <Submit isSubmitting={isSubmitting} label="Propose credential rotation" />
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
    () => (data?.items ?? []).find((policy) => policy.policy_type === ACTION_TOOLS_POLICY_TYPE) ?? null,
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
              setNotice("Action policy change proposed — pending approval by another principal.");
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
    <article className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-[18px] font-semibold text-ink-primary">action_tools</h2>
        <span className="shrink-0 rounded border border-border-subtle px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
          v{policy.version} · {policy.status}
        </span>
      </div>
      <div className="mt-4 grid gap-2">
        <Field label="Approved by" value={policy.approved_by} />
        <Field label="Effective from" value={policy.effective_from} />
      </div>
      <pre className="mt-3 max-h-72 overflow-auto rounded border border-border-subtle bg-surface-raised p-3 text-[11px] leading-relaxed text-ink-secondary">
        {JSON.stringify(policy.parameters, null, 2)}
      </pre>
    </article>
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

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      const refundConfidenceRaw = String(form.get("refund_confidence_gte") || "").trim();
      const body = buildActionPolicyChangePayload({
        policyId: policy?.policy_id,
        effectiveFrom: policy ? undefined : new Date(String(form.get("effective_from") || "")).toISOString(),
        warrantyConfidenceGte: Number(form.get("warranty_confidence_gte")),
        warrantyIssueCategories: parseList(String(form.get("warranty_issue_category_in") || "")),
        warrantyElse: String(form.get("warranty_else") || "require_approval") as PolicyDecision,
        replacementAlways: String(form.get("replacement_always") || "require_approval") as PolicyDecision,
        refundAmountCentsLte: Number(form.get("refund_amount_cents_lte")),
        refundConfidenceGte: refundConfidenceRaw === "" ? null : Number(refundConfidenceRaw),
        refundElse: String(form.get("refund_else") || "require_approval") as PolicyDecision,
        warehouseAllowSeverities: parseList(String(form.get("warehouse_allow_severity_in") || "")),
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
        Governed change — applied only after a different principal approves. A
        malformed policy is rejected at propose; the error appears below.
      </p>
      {error && <FormError message={error} />}
      {!policy && (
        <Text name="effective_from" label="Effective from" type="datetime-local" defaultValue={nowLocal()} required />
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
          defaultValue={existing.refundConfidenceGte == null ? "" : String(existing.refundConfidenceGte)}
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

function GovernedNotice() {
  return (
    <div className="mb-4 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] leading-relaxed text-ink-secondary">
      Edits here are <strong>governed</strong>: they become change requests that stay
      pending until a different principal approves them, then apply. This is dual
      control — not a direct write.
    </div>
  );
}

function ProposedNotice({ message, onDismiss }: { message: string; onDismiss: () => void }) {
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

function Header({
  eyebrow,
  title,
  actionLabel,
  onAction,
}: {
  eyebrow: string;
  title: string;
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <>
      <div className="eyebrow text-ink-tertiary mb-2">{eyebrow}</div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="font-display text-[32px] font-semibold text-ink-primary">{title}</h1>
        <button
          onClick={onAction}
          className="h-11 rounded border border-border-subtle bg-surface px-4 text-[13px] text-ink-secondary hover:border-border-defined hover:text-ink-primary sm:h-10"
        >
          {actionLabel}
        </button>
      </div>
    </>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">{label}</div>
      <div className="mt-1 break-words text-[13px] leading-relaxed text-ink-secondary">{value}</div>
    </div>
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

function Fieldset({ legend, children }: { legend: string; children: React.ReactNode }) {
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
  defaultValue = "",
  required = false,
}: {
  label: string;
  name: string;
  type?: string;
  defaultValue?: string;
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
        defaultValue={defaultValue}
        required={required}
        className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
      />
    </label>
  );
}

/**
 * Write-only credential input. Never receives a defaultValue — the current
 * credential is never read into the form, never displayed. Blank = keep.
 */
function WriteOnlyInput({ name, label }: { name: string; label: string }) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <input
        name={name}
        type="password"
        autoComplete="new-password"
        placeholder={KEEP_CURRENT_PLACEHOLDER}
        className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
      />
    </label>
  );
}

function Select({
  label,
  name,
  defaultValue,
  options,
}: {
  label: string;
  name: string;
  defaultValue: string;
  options: string[];
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <select
        name={name}
        defaultValue={defaultValue}
        className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
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

function JsonArea({
  label,
  name,
  defaultValue,
}: {
  label: string;
  name: string;
  defaultValue: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <textarea
        name={name}
        defaultValue={defaultValue}
        rows={6}
        className="w-full rounded border border-border-subtle bg-surface-raised px-3 py-2 font-mono text-[12px] leading-relaxed text-ink-primary focus:outline-none focus:border-gold-primary"
      />
    </label>
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

function FormError({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
      {message}
    </div>
  );
}

// ─── helpers ──────────────────────────────────────────────────────────────

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Expected a JSON object");
  }
  return parsed as Record<string, unknown>;
}

function parseStatusCodes(value: string): number[] {
  const codes = value
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((code) => Number.isInteger(code));
  return codes.length > 0 ? codes : [200];
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
      asNumber(refundAllow.refund_amount_cents_lte) ?? asNumber(refundAllow.amount_cents_lte),
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
