"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ElementType } from "react";
import {
  AlertTriangle,
  Ban,
  LockKeyhole,
  Power,
  Snowflake,
  X,
} from "lucide-react";
import {
  deactivateCrisisDeployment,
  deployCrisisRule,
  formatApiError,
  getCrisisTickerUrl,
  listActiveCrisisDeployments,
  type CrisisDeployment,
  type CrisisInterceptEvent,
  type CrisisTemplate,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type TemplateConfig = {
  template: CrisisTemplate;
  label: string;
  decision: string;
  icon: ElementType;
  tone: string;
};

const templates: TemplateConfig[] = [
  {
    template: "block_sku",
    label: "Block Product",
    decision: "DENY",
    icon: LockKeyhole,
    tone: "border-orange-500/35 bg-orange-500/10 text-orange-700 dark:text-orange-300",
  },
  {
    template: "halt_refunds",
    label: "Pause Refunds",
    decision: "REQUIRE_APPROVAL",
    icon: Ban,
    tone: "border-red-alert/35 bg-red-alert/10 text-red-alert",
  },
  {
    template: "escalate_all",
    label: "Escalate Everything",
    decision: "ESCALATE",
    icon: AlertTriangle,
    tone: "border-warning-amber/40 bg-warning-amber/10 text-warning-amber",
  },
  {
    template: "freeze_category",
    label: "Freeze Category",
    decision: "DENY",
    icon: Snowflake,
    tone: "border-blue-system/35 bg-blue-system/10 text-blue-system",
  },
];

const ttlOptions = [
  { label: "30m", value: 30 },
  { label: "1h", value: 60 },
  { label: "4h", value: 240 },
  { label: "24h", value: 1440 },
  { label: "No expiry", value: 0 },
];

const categories = [
  "account_issue",
  "charging_issue",
  "connectivity_issue",
  "product_defect",
  "refund_issue",
  "unknown_issue",
];

export function CrisisControlPanel() {
  const [deployments, setDeployments] = useState<CrisisDeployment[]>([]);
  const [modalTemplate, setModalTemplate] = useState<CrisisTemplate | null>(null);
  const [activeError, setActiveError] = useState<string | null>(null);
  const [busyDeployment, setBusyDeployment] = useState<string | null>(null);
  const loadActive = useCallback(() => {
    listActiveCrisisDeployments()
      .then((records) => {
        setDeployments(records);
        setActiveError(null);
      })
      .catch((error: unknown) => setActiveError(formatApiError(error)));
  }, []);

  useEffect(() => {
    loadActive();
    const interval = window.setInterval(loadActive, 30_000);
    return () => window.clearInterval(interval);
  }, [loadActive]);

  const deactivate = async (deployment: CrisisDeployment) => {
    setBusyDeployment(deployment.deployment_id);
    try {
      await deactivateCrisisDeployment(deployment.deployment_id);
      loadActive();
    } catch (error: unknown) {
      setActiveError(formatApiError(error));
    } finally {
      setBusyDeployment(null);
    }
  };

  return (
    <section className="mb-6 space-y-4">
      <div className="rounded-md border border-red-alert/25 bg-red-alert/10 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-red-alert">
          <AlertTriangle className="h-4 w-4" strokeWidth={1.8} />
          <span>Crisis Mode</span>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-4">
        {templates.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.template}
              type="button"
              onClick={() => setModalTemplate(item.template)}
              className={cn(
                "flex h-[76px] items-center gap-3 rounded-md border px-4 text-left transition-colors hover:border-border-strong",
                item.tone
              )}
            >
              <Icon className="h-5 w-5 shrink-0" strokeWidth={1.8} />
              <span className="min-w-0">
                <span className="block truncate font-technical text-[12px] font-semibold">
                  {item.label}
                </span>
                <span className="block truncate text-[12px] opacity-80">
                  {item.decision}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <ActiveDeployments
        deployments={deployments}
        error={activeError}
        busyDeployment={busyDeployment}
        onDeactivate={(deployment) => void deactivate(deployment)}
      />
      <InterceptTicker />

      {modalTemplate && (
        <CrisisDeployModal
          template={modalTemplate}
          onClose={() => setModalTemplate(null)}
          onDeployed={() => {
            setModalTemplate(null);
            loadActive();
          }}
        />
      )}
    </section>
  );
}

function CrisisDeployModal({
  template,
  onClose,
  onDeployed,
}: {
  template: CrisisTemplate;
  onClose: () => void;
  onDeployed: () => void;
}) {
  const config = templates.find((item) => item.template === template) ?? templates[0];
  const ModalIcon = config.icon;
  const [sku, setSku] = useState("");
  const [category, setCategory] = useState(categories[0]);
  const [ttlMinutes, setTtlMinutes] = useState(30);
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const scope = useMemo(() => {
    if (template === "block_sku") return { sku: sku.trim() };
    if (template === "freeze_category") return { category };
    return {};
  }, [category, sku, template]);
  const preview = previewText(template, scope);
  const scopeReady =
    template === "block_sku"
      ? sku.trim().length > 0
      : template === "freeze_category"
        ? category.length > 0
        : true;
  const canDeploy = confirm === "CONFIRM" && scopeReady && !submitting;

  const deploy = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await deployCrisisRule({
        template,
        scope,
        ttl_minutes: ttlMinutes,
      });
      onDeployed();
    } catch (caught: unknown) {
      setError(formatApiError(caught));
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
      <div className="w-full max-w-[560px] rounded-md border border-border-defined bg-surface shadow-overlay">
        <div className="flex items-center justify-between border-b border-border-subtle px-5 py-4">
          <div className="flex items-center gap-3">
            <span className={cn("flex h-9 w-9 items-center justify-center rounded-md border", config.tone)}>
              <ModalIcon className="h-4 w-4" strokeWidth={1.8} />
            </span>
            <div>
              <div className="font-technical text-[12px] font-semibold text-ink-primary">
                {config.label}
              </div>
              <div className="text-[12px] text-ink-tertiary">{config.decision}</div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border-subtle text-ink-secondary hover:border-border-defined hover:text-ink-primary"
            aria-label="Close"
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          {template === "block_sku" && (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink-secondary">SKU</span>
              <input
                value={sku}
                onChange={(event) => setSku(event.target.value)}
                className="h-10 w-full rounded-md border border-border-subtle bg-surface-raised px-3 font-technical text-[13px] text-ink-primary outline-none focus:border-red-alert"
              />
            </label>
          )}
          {template === "freeze_category" && (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink-secondary">Category</span>
              <select
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className="h-10 w-full rounded-md border border-border-subtle bg-surface-raised px-3 font-technical text-[13px] text-ink-primary outline-none focus:border-blue-system"
              >
                {categories.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div>
            <div className="mb-2 text-[12px] font-medium text-ink-secondary">TTL</div>
            <div className="grid grid-cols-5 gap-2">
              {ttlOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setTtlMinutes(option.value)}
                  className={cn(
                    "h-9 rounded-md border px-2 font-technical text-[11px]",
                    ttlMinutes === option.value
                      ? "border-red-alert bg-red-alert/10 text-red-alert"
                      : "border-border-subtle text-ink-secondary hover:border-border-defined"
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-md border border-border-subtle bg-surface-raised p-3 text-[13px] text-ink-body">
            {preview}
          </div>

          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink-secondary">
              Type CONFIRM
            </span>
            <input
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              className="h-10 w-full rounded-md border border-border-subtle bg-surface-raised px-3 font-technical text-[13px] text-ink-primary outline-none focus:border-red-alert"
            />
          </label>
          {error && <div className="text-[12px] text-red-alert">{error}</div>}
        </div>

        <div className="flex justify-end gap-2 border-t border-border-subtle px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="h-9 rounded-md border border-border-subtle px-4 text-[12px] text-ink-secondary hover:border-border-defined"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canDeploy}
            onClick={() => void deploy()}
            className="h-9 rounded-md bg-red-alert px-4 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-45"
          >
            Deploy Crisis Rule
          </button>
        </div>
      </div>
    </div>
  );
}

function ActiveDeployments({
  deployments,
  error,
  busyDeployment,
  onDeactivate,
}: {
  deployments: CrisisDeployment[];
  error: string | null;
  busyDeployment: string | null;
  onDeactivate: (deployment: CrisisDeployment) => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  return (
    <div className="overflow-hidden rounded-md border border-border-subtle bg-surface">
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
        <div>
          <div className="heading-section">Active Deployments</div>
          <div className="text-meta">{deployments.length} active</div>
        </div>
      </div>
      {error && <div className="border-b border-border-subtle px-4 py-2 text-[12px] text-red-alert">{error}</div>}
      <div className="overflow-x-auto">
        <table className="cc-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>Scope</th>
              <th>Deployed by</th>
              <th>Time ago</th>
              <th>Expires in</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {deployments.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-ink-tertiary">
                  No active crisis deployments
                </td>
              </tr>
            ) : (
              deployments.map((deployment) => (
                <tr key={deployment.deployment_id}>
                  <td>
                    <span className="rounded border border-red-alert/25 bg-red-alert/10 px-2 py-1 text-[11px] text-red-alert">
                      {templateLabel(deployment.template)}
                    </span>
                  </td>
                  <td>{formatScope(deployment)}</td>
                  <td>{deployment.deployed_by}</td>
                  <td>{relativeTime(deployment.deployed_at, now)}</td>
                  <td>{expiresIn(deployment.expires_at, now)}</td>
                  <td>
                    <button
                      type="button"
                      onClick={() => onDeactivate(deployment)}
                      disabled={busyDeployment === deployment.deployment_id}
                      className="inline-flex h-8 items-center gap-1.5 rounded-md border border-red-alert/30 px-2 text-[11px] text-red-alert disabled:opacity-45"
                    >
                      <Power className="h-3.5 w-3.5" strokeWidth={1.8} />
                      DEACTIVATE
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InterceptTicker() {
  const [items, setItems] = useState<CrisisInterceptEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    const source = new EventSource(getCrisisTickerUrl());
    const onEvent = (event: MessageEvent) => {
      if (pausedRef.current) return;
      try {
        const parsed = JSON.parse(event.data) as CrisisInterceptEvent;
        setItems((current) => [parsed, ...current].slice(0, 50));
      } catch {
        return;
      }
    };
    source.addEventListener("intercept", onEvent);
    source.onmessage = onEvent;
    return () => source.close();
  }, []);

  return (
    <div
      className="rounded-md border border-border-subtle bg-surface"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
        <div className="heading-section">Intercept Ticker</div>
        <span className="rounded border border-red-alert/25 bg-red-alert/10 px-2 py-1 font-technical text-[11px] text-red-alert">
          {items.length} intercepted this session
        </span>
      </div>
      <div className="max-h-[220px] overflow-y-auto p-3 font-technical text-[12px] text-ink-body">
        {items.length === 0 ? (
          <div className="text-ink-tertiary">No crisis intercepts in this session</div>
        ) : (
          <div className="space-y-2">
            {items.map((item, index) => (
              <div
                key={`${item.execution_id}-${item.intercepted_at}-${index}`}
                className="rounded border border-border-subtle bg-surface-raised px-3 py-2"
              >
                [{formatTime(item.intercepted_at)}] {item.template} intercepted execution{" "}
                {item.execution_id}
                {item.category ? ` (${item.category})` : ""}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function previewText(template: CrisisTemplate, scope: Record<string, unknown>) {
  if (template === "block_sku") {
    return `Will DENY all tickets mentioning SKU ${String(scope.sku || "").trim() || "..."}`;
  }
  if (template === "halt_refunds") {
    return "Will REQUIRE_APPROVAL for refund request tool actions";
  }
  if (template === "escalate_all") {
    return "Will ESCALATE all diagnostic and action governance subjects";
  }
  return `Will DENY tickets classified as ${String(scope.category || "").trim() || "..."}`;
}

function templateLabel(value: string) {
  const known: Record<string, string> = {
    block_sku: "Block Product",
    halt_refunds: "Pause Refunds",
    escalate_all: "Escalate Everything",
    freeze_category: "Freeze Category",
  };
  return known[value] ?? value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatScope(deployment: CrisisDeployment) {
  if (deployment.template === "block_sku") return String(deployment.scope.sku || "");
  if (deployment.template === "freeze_category") return String(deployment.scope.category || "");
  return "tenant-wide";
}

function relativeTime(value: string, now: number) {
  const diff = Math.max(0, now - new Date(value).getTime());
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

function expiresIn(value: string | null, now: number) {
  if (!value) return "no expiry";
  const diff = new Date(value).getTime() - now;
  if (diff <= 0) return "expired";
  const minutes = Math.ceil(diff / 60_000);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.ceil(minutes / 60)}h`;
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
