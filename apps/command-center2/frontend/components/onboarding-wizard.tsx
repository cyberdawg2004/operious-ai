"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Check,
  Clock,
  Lock,
  ExternalLink,
} from "lucide-react";
import {
  formatApiError,
  listChannelConfigurations,
  listConfigChangeRequests,
  listConnectorConfigurations,
  listGovernancePolicies,
  proposeConfigChangeRequest,
} from "@/lib/api";
import {
  buildChannelChangePayload,
  CONNECTOR_TYPE_OPTIONS,
} from "@/lib/config-change-payloads";
import {
  computeOnboardingSteps,
  findActiveActionPolicy,
  tenantIsOperational,
  type OnboardingSnapshot,
  type OnboardingStep,
  type OnboardingStepState,
} from "@/lib/onboarding-state";
import { dashboardRoutes } from "@/lib/dashboard-routes";
import { useAuthSession } from "@/lib/use-auth-session";
import { useApiResource } from "@/lib/use-api-resource";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";

const CHANNEL_SECRET_KEYS: Record<string, { key: string; label: string }> = {
  email: { key: "smtp_password", label: "SMTP Password" },
  whatsapp: { key: "access_token", label: "Access Token" },
  voice: { key: "auth_token", label: "Auth Token" },
  zendesk: { key: "api_token", label: "API Token" },
  jira: { key: "api_token", label: "API Token" },
  linear: { key: "api_key", label: "API Key" },
  shopify: { key: "access_token", label: "Admin API Access Token" },
  shulex: { key: "api_key", label: "API Key" },
  lark: { key: "app_secret", label: "App Secret" },
};

export function OnboardingWizard() {
  const authSession = useAuthSession();
  const principal = authSession.principal;
  const tenantId = principal?.tenant_id ?? null;
  const scoped = Boolean(tenantId);

  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // Phase B reads (channels/connectors/policies/change-requests) are
  // tenant-scoped and 400 with tenant_axis_missing if the session is not scoped
  // to a tenant. Fetch them ONLY when scoped (the residual re-auth guard).
  const loadSnapshot = useCallback(async (): Promise<
    Omit<OnboardingSnapshot, "principal">
  > => {
    if (!scoped) {
      return { channels: [], connectors: [], policies: [], changeRequests: [] };
    }
    const [channels, connectors, policies, proposed, approved] = await Promise.all([
      listChannelConfigurations(),
      listConnectorConfigurations({ status: "active" }),
      listGovernancePolicies(),
      listConfigChangeRequests({ status: "PROPOSED" }),
      listConfigChangeRequests({ status: "APPROVED" }),
    ]);
    return {
      channels: channels.items,
      connectors: connectors.items,
      policies: policies.items,
      changeRequests: [...proposed.items, ...approved.items],
    };
  }, [scoped]);

  const { data, error, isLoading, reload } = useApiResource(loadSnapshot);

  const snapshot: OnboardingSnapshot = useMemo(
    () => ({
      principal,
      channels: data?.channels ?? [],
      connectors: data?.connectors ?? [],
      policies: data?.policies ?? [],
      changeRequests: data?.changeRequests ?? [],
    }),
    [principal, data]
  );

  const steps = useMemo(() => computeOnboardingSteps(snapshot), [snapshot]);
  const operational = tenantIsOperational(snapshot);
  const activePolicy = findActiveActionPolicy(snapshot.policies);

  const refreshAll = () => {
    authSession.reload();
    reload();
  };

  if (!scoped) {
    return (
      <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
        <WizardHeader />
        <EmptyState
          title="Open a workspace first"
          message="Workspace setup is only available after you open a specific workspace."
        />
      </main>
    );
  }

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <WizardHeader />

      <div className="mb-5 rounded-lg border border-border-subtle bg-surface-raised p-4 text-[13px] text-ink-secondary">
        You are setting up this workspace:{" "}
        <strong className="text-ink-primary">{tenantId}</strong>. Each step is a
        requested change that must be approved by another teammate before it goes live.
      </div>

      <OperationalBanner operational={operational} target={tenantId ?? ""} />

      {notice && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-md border border-gold-primary/40 bg-gold-bg px-3 py-2 text-[13px] text-ink-primary">
          <span>{notice}</span>
          <button
            onClick={() => setNotice(null)}
            className="h-7 rounded border border-border-subtle px-2 text-[12px] text-ink-secondary hover:text-ink-primary"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && <ErrorState title="Onboarding state unavailable" message={error} onAction={refreshAll} />}
      {isLoading && <LoadingState label="Loading workspace setup..." />}

      {!isLoading && (
        <div className="space-y-6">
          <PhaseBlock
            label="Set up this workspace"
            hint="Each requested change is reviewed before it becomes active."
          >
            {steps.map((step) => (
              <StepCard key={step.id} step={step} index={stepIndex(step.id)}>
                <PhaseBAction
                  step={step}
                  onOpenChannelModal={() => setChannelModalOpen(true)}
                />
              </StepCard>
            ))}
          </PhaseBlock>

          <ApproverLink />
        </div>
      )}

      {channelModalOpen && (
        <ChannelCreateModal
          onClose={() => setChannelModalOpen(false)}
          onProposed={() => {
            setNotice("Channel setup requested. It will go live after approval.");
            setChannelModalOpen(false);
            reload();
          }}
        />
      )}

      {activePolicy && (
        <p className="mt-4 text-[12px] text-ink-tertiary">
          Active action policy: v{activePolicy.version} · approved by {activePolicy.approved_by}
        </p>
      )}
    </main>
  );
}

// ─── Phase B action (compose the proven editors) ──────────────────────────

function PhaseBAction({
  step,
  onOpenChannelModal,
}: {
  step: OnboardingStep;
  onOpenChannelModal: () => void;
}) {
  const router = useRouter();
  if (step.state === "blocked") {
    return (
      <p className="text-[12px] text-ink-tertiary">
        Finish the earlier step first.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {step.pendingChange && (
        <div className="rounded border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] text-ink-secondary">
          Change request pending. Status{" "}
          <strong className="text-ink-primary">{step.pendingChange.status}</strong>. Open Change
          Approvals to review it and make it active.
        </div>
      )}
      {step.id === "channel" && step.state !== "complete" && (
        <button
          onClick={onOpenChannelModal}
          className="inline-flex h-9 items-center gap-2 rounded bg-gold-primary px-3 text-[12px] font-semibold text-white hover:bg-gold-muted"
        >
          Request channel setup <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.8} />
        </button>
      )}
      {(step.id === "connector" || step.id === "connector-credential") &&
        step.state !== "complete" && (
          <button
            onClick={() => router.push(dashboardRoutes.connectors)}
            className="inline-flex h-9 items-center gap-2 rounded border border-border-subtle px-3 text-[12px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
          >
            Open Connected Systems <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.8} />
          </button>
        )}
      {step.id === "action-policy" && step.state !== "complete" && (
          <button
            onClick={() => router.push(dashboardRoutes["action-policy"])}
            className="inline-flex h-9 items-center gap-2 rounded border border-border-subtle px-3 text-[12px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
          >
          Open Action Rules <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.8} />
          </button>
      )}
      {step.state === "complete" && (
        <p className="text-[12px] text-green-success">Active.</p>
      )}
    </div>
  );
}

function ApproverLink() {
  const router = useRouter();
  return (
    <div className="rounded-lg border border-border-subtle bg-surface p-4">
      <p className="text-[13px] leading-relaxed text-ink-secondary">
        Every setup change needs a second person to approve it before it goes live.
      </p>
      <button
        onClick={() => router.push(dashboardRoutes["config-approvals"])}
        className="mt-3 inline-flex h-9 items-center gap-2 rounded border border-gold-primary/40 px-3 text-[12px] text-gold-primary hover:bg-gold-primary/10"
      >
        Open Change Approvals <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} />
      </button>
    </div>
  );
}

// ─── Governed channel create modal ────────────────────────────────────────

function ChannelCreateModal({
  onClose,
  onProposed,
}: {
  onClose: () => void;
  onProposed: () => void;
}) {
  const [channelType, setChannelType] = useState<string>(CONNECTOR_TYPE_OPTIONS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const secret = CHANNEL_SECRET_KEYS[channelType] ?? { key: "secret", label: "Secret" };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      const body = buildChannelChangePayload({
        channelType,
        routingAddress: String(form.get("routing_address") || ""),
        credentials: { [secret.key]: String(form.get(secret.key) || "") },
        webhookSecret: String(form.get("webhook_secret") || ""),
      });
      await proposeConfigChangeRequest(body);
      onProposed();
    } catch (caught: unknown) {
      setError(formatApiError(caught));
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 sm:p-6">
      <div className="max-h-[88dvh] w-full max-w-2xl overflow-y-auto rounded-lg border border-border-subtle bg-surface p-4 shadow-elevated sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-[22px] font-semibold text-ink-primary">
            Propose Channel (governed)
          </h2>
          <button
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded border border-border-subtle text-ink-tertiary hover:text-ink-primary"
            aria-label="Close"
          >
            X
          </button>
        </div>
        <p className="mb-4 text-[13px] leading-relaxed text-ink-secondary">
          In production, channels are added through a review step. Request the
          change here, then another manager approves it before it goes live.
        </p>
        <form onSubmit={submit} className="space-y-4">
          {error && <FormError message={error} />}
          <label className="block">
            <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
              Channel type
            </span>
            <select
              value={channelType}
              onChange={(event) => setChannelType(event.target.value)}
              className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
            >
              {CONNECTOR_TYPE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <TextField name="routing_address" label="Routing address" required />
          <SecretField name={secret.key} label={secret.label} />
          <SecretField name="webhook_secret" label="Webhook secret (blank if unused)" />
          <button
            type="submit"
            disabled={busy}
            className="inline-flex h-11 items-center justify-center rounded bg-gold-primary px-4 text-[13px] font-semibold text-white hover:bg-gold-muted disabled:opacity-60"
          >
            {busy ? "Proposing..." : "Propose channel change"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ─── Presentation primitives ──────────────────────────────────────────────

function WizardHeader() {
  return (
    <>
      <div className="eyebrow text-ink-tertiary mb-2">ONBOARDING · CONFIGURE TENANT</div>
      <h1 className="mb-2 font-display text-[32px] font-semibold text-ink-primary">
        Configure This Tenant
      </h1>
      <p className="mb-5 max-w-3xl text-[13px] leading-relaxed text-ink-secondary">
        Take the tenant your session is scoped to from inert to operational through the
        governed config flow (channel → connector → credential → action policy). Step state
        is derived from real backend data — a step is complete only when its change request is
        applied. (Creating a tenant is a platform operation, done in the Platform Console.)
      </p>
    </>
  );
}

function OperationalBanner({ operational, target }: { operational: boolean; target: string }) {
  return (
    <div
      className={
        operational
          ? "mb-5 rounded-lg border border-green-success/40 bg-surface p-4 text-[13px] text-green-success"
          : "mb-5 rounded-lg border border-border-subtle bg-surface p-4 text-[13px] text-ink-secondary"
      }
    >
      {operational ? (
        <span>
          <strong>{target}</strong> is operational — an action policy is active, so the tenant
          can act.
        </span>
      ) : (
        <span>
          <strong>{target || "Target tenant"}</strong> is inert / fail-closed — it cannot act
          until an action policy is applied.
        </span>
      )}
    </div>
  );
}

function PhaseBlock({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-3">
        <h2 className="font-display text-[20px] font-semibold text-ink-primary">{label}</h2>
        <p className="text-[12px] text-ink-tertiary">{hint}</p>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function StepCard({
  step,
  index,
  children,
}: {
  step: OnboardingStep;
  index: number;
  children: React.ReactNode;
}) {
  return (
    <article className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-border-subtle font-mono text-[12px] text-ink-tertiary">
            {index}
          </span>
          <h3 className="text-[16px] font-semibold text-ink-primary">{step.title}</h3>
        </div>
        <StateBadge state={step.state} />
      </div>
      <div className="mt-3 pl-10">{children}</div>
    </article>
  );
}

function StateBadge({ state }: { state: OnboardingStepState }) {
  const map: Record<OnboardingStepState, { label: string; cls: string; icon: React.ReactNode }> = {
    blocked: {
      label: "Blocked",
      cls: "border-border-subtle text-ink-tertiary",
      icon: <Lock className="h-3 w-3" strokeWidth={1.8} />,
    },
    available: {
      label: "Available",
      cls: "border-gold-primary/40 text-gold-primary",
      icon: <ArrowRight className="h-3 w-3" strokeWidth={1.8} />,
    },
    "in-progress": {
      label: "In progress",
      cls: "border-gold-primary/40 text-gold-primary",
      icon: <Clock className="h-3 w-3" strokeWidth={1.8} />,
    },
    complete: {
      label: "Complete",
      cls: "border-green-success/40 text-green-success",
      icon: <Check className="h-3 w-3" strokeWidth={1.8} />,
    },
  };
  const meta = map[state];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded border bg-surface-raised px-2 py-1 font-technical text-[10px] uppercase tracking-[0.10em] ${meta.cls}`}
    >
      {meta.icon}
      {meta.label}
    </span>
  );
}

function TextField({ name, label, required = false }: { name: string; label: string; required?: boolean }) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <input
        name={name}
        required={required}
        className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
      />
    </label>
  );
}

function SecretField({ name, label }: { name: string; label: string }) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <input
        name={name}
        type="password"
        autoComplete="new-password"
        placeholder="Write-only — never displayed"
        className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
      />
    </label>
  );
}

function FormError({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
      {message}
    </div>
  );
}

function stepIndex(id: OnboardingStep["id"]): number {
  const order: OnboardingStep["id"][] = [
    "channel",
    "connector",
    "connector-credential",
    "action-policy",
  ];
  return order.indexOf(id) + 1;
}
