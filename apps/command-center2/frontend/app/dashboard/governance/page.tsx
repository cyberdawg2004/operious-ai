"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ShieldAlert } from "lucide-react";
import { CrisisControlPanel } from "@/components/crisis-control-panel";
import { GovernancePoliciesView } from "@/components/integration-views";
import {
  formatApiError,
  listActiveCrisisDeployments,
  listCrisisEvents,
  type CrisisDeployment,
  type CrisisEvent,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export default function DashboardGovernancePage() {
  return (
    <GovernancePoliciesView
      headerAddon={<CrisisControlPanel />}
      footerAddon={<EmergencyRuleHistory />}
    />
  );
}

function EmergencyRuleHistory() {
  const [deployments, setDeployments] = useState<CrisisDeployment[]>([]);
  const [events, setEvents] = useState<CrisisEvent[]>([]);
  const [activeError, setActiveError] = useState<string | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);

  const loadActive = useCallback(() => {
    listActiveCrisisDeployments()
      .then((records) => {
        setDeployments(records);
        setActiveError(null);
      })
      .catch((error: unknown) => setActiveError(formatApiError(error)));
  }, []);

  const loadEvents = useCallback(() => {
    listCrisisEvents({ limit: 100 })
      .then((records) => {
        setEvents(records);
        setEventsError(null);
      })
      .catch((error: unknown) => setEventsError(formatApiError(error)));
  }, []);

  useEffect(() => {
    loadActive();
    const interval = window.setInterval(loadActive, 30_000);
    return () => window.clearInterval(interval);
  }, [loadActive]);

  useEffect(() => {
    loadEvents();
    const interval = window.setInterval(loadEvents, 60_000);
    return () => window.clearInterval(interval);
  }, [loadEvents]);

  return (
    <div className="mt-8 space-y-6">
      <h2 className="text-sm font-semibold text-ink-primary">Emergency Rule History</h2>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-red-alert" strokeWidth={1.8} />
          <h3 className="text-sm font-semibold text-ink-primary">Active Now</h3>
        </div>
        {activeError ? (
          <div className="rounded-md border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-sm text-red-alert">
            {activeError}
          </div>
        ) : deployments.length === 0 ? (
          <div className="flex items-center gap-2 rounded-md border border-green-500/25 bg-green-500/10 px-3 py-2 text-sm font-medium text-green-700 dark:text-green-300">
            <CheckCircle2 className="h-4 w-4" strokeWidth={1.8} />
            No active crisis rules
          </div>
        ) : (
          <div className="overflow-hidden rounded-md border border-border-subtle">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-raised text-[11px] uppercase text-ink-tertiary">
                <tr>
                  <th className="px-3 py-2 font-semibold">Template</th>
                  <th className="px-3 py-2 font-semibold">Scope</th>
                  <th className="px-3 py-2 font-semibold">Deployed by</th>
                  <th className="px-3 py-2 font-semibold">Time active</th>
                  <th className="px-3 py-2 font-semibold">Expires in</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {deployments.map((deployment) => (
                  <tr key={deployment.deployment_id}>
                    <td className="px-3 py-2 font-technical text-xs font-semibold text-ink-primary">
                      {templateLabel(deployment.template)}
                    </td>
                    <td className="px-3 py-2 text-ink-secondary">
                      {scopeLabel(deployment.scope)}
                    </td>
                    <td className="px-3 py-2 text-ink-secondary">
                      {deployment.deployed_by}
                    </td>
                    <td className="px-3 py-2 text-ink-secondary">
                      {relativeTime(deployment.deployed_at)}
                    </td>
                    <td className="px-3 py-2 text-ink-secondary">
                      {expiresIn(deployment.expires_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-ink-primary">
          Event Log <span className="text-ink-tertiary">(last 30 days)</span>
        </h3>
        {eventsError ? (
          <div className="rounded-md border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-sm text-red-alert">
            {eventsError}
          </div>
        ) : events.length === 0 ? (
          <div className="flex items-center gap-2 rounded-md border border-green-500/25 bg-green-500/10 px-3 py-2 text-sm font-medium text-green-700 dark:text-green-300">
            <CheckCircle2 className="h-4 w-4" strokeWidth={1.8} />
            No crisis events in the last 30 days
          </div>
        ) : (
          <div className="overflow-hidden rounded-md border border-border-subtle">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-raised text-[11px] uppercase text-ink-tertiary">
                <tr>
                  <th className="px-3 py-2 font-semibold">When</th>
                  <th className="px-3 py-2 font-semibold">Template</th>
                  <th className="px-3 py-2 font-semibold">Kind</th>
                  <th className="px-3 py-2 font-semibold">Scope</th>
                  <th className="px-3 py-2 font-semibold">Actor</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {events.map((event) => (
                  <tr key={event.event_id}>
                    <td className="px-3 py-2 text-ink-secondary">
                      {relativeTime(event.occurred_at)}
                    </td>
                    <td className="px-3 py-2 font-technical text-xs font-semibold text-ink-primary">
                      {templateLabel(event.template)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "inline-flex rounded-sm px-2 py-1 text-[11px] font-semibold uppercase",
                          eventKindTone(event.event_kind)
                        )}
                      >
                        {event.event_kind}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-ink-secondary">
                      {scopeLabel(event.scope)}
                    </td>
                    <td className="px-3 py-2 text-ink-secondary">{event.actor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
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

function scopeLabel(scope: Record<string, unknown>) {
  if (typeof scope.sku === "string" && scope.sku) return `SKU ${scope.sku}`;
  if (typeof scope.category === "string" && scope.category) {
    return String(scope.category);
  }
  return "tenant-wide";
}

function relativeTime(value: string) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function expiresIn(value: string | null) {
  if (!value) return "No expiry";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  const seconds = Math.max(0, Math.floor((timestamp - Date.now()) / 1000));
  if (seconds <= 0) return "Expired";
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.ceil(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.ceil(hours / 24)}d`;
}

function eventKindTone(kind: CrisisEvent["event_kind"]) {
  if (kind === "deployed") return "bg-red-100 text-red-800";
  if (kind === "deactivated") return "bg-green-100 text-green-800";
  return "bg-gray-100 text-gray-700";
}
