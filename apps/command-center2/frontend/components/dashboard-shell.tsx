"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Command,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  UserCircle2,
} from "lucide-react";
import { Sidebar } from "@/components/sidebar";
import { CommandPalette } from "@/components/command-palette";
import type { TraceLookup } from "@/components/trace-inspector";
import {
  getConfiguredOperatorLabel,
  getConfiguredPrincipalId,
  getConfiguredTenantId,
  listActionApprovals,
  listActiveCrisisDeployments,
  listSemanticCircuitStates,
} from "@/lib/api";
import { dashboardRoutes, type DashboardViewId } from "@/lib/dashboard-routes";
import { useAuthSession } from "@/lib/use-auth-session";
import { cn } from "@/lib/utils";

const viewMeta: Record<DashboardViewId, { eyebrow: string; title: string; description: string }> = {
  operations: {
    eyebrow: "Operations",
    title: "Operations Queue",
    description: "Live execution sessions, lifecycle state, latency, and governance outcomes.",
  },
  conversations: {
    eyebrow: "Operations",
    title: "Conversations",
    description: "Active customer sessions, live turns, and operator takeover.",
  },
  "queue-status": {
    eyebrow: "Operations",
    title: "Queue Status",
    description: "Global queue depth, oldest age, and health across all worker queues.",
  },
  "dlq-inspector": {
    eyebrow: "Operations",
    title: "DLQ Inspector",
    description: "Tenant-scoped dead-letter task records with replay controls.",
  },
  fraud: {
    eyebrow: "Operations",
    title: "Fraud Monitoring",
    description: "Semantic circuit states, quarantine clusters, and fraud review.",
  },
  trace: {
    eyebrow: "Observability",
    title: "Trace Inspector",
    description: "Replay recorded spans and inspect substrate-level execution evidence.",
  },
  supervisor: {
    eyebrow: "Operations",
    title: "Supervisor Inbox",
    description: "Risky inspections, QA score evidence, and trainer recommendations.",
  },
  approvals: {
    eyebrow: "Governance",
    title: "Approval Inbox",
    description: "Pending manager approvals for governed action tools.",
  },
  cognition: {
    eyebrow: "Cognition",
    title: "Cognition Hub",
    description: "Review agent proposals, confidence signals, and escalation pathways.",
  },
  knowledge: {
    eyebrow: "Knowledge",
    title: "Knowledge Base",
    description: "Tenant-scoped source material and SOP intelligence.",
  },
  governance: {
    eyebrow: "Governance",
    title: "Governance Policies",
    description: "Policy records, approval status, and effective runtime configuration.",
  },
  crisis: {
    eyebrow: "Governance",
    title: "Crisis History",
    description: "Emergency rule activity, active deployments, and audit events.",
  },
  topology: {
    eyebrow: "Topology",
    title: "Topology",
    description: "Configured agent topology for the current tenant scope.",
  },
  channels: {
    eyebrow: "Boundary",
    title: "Channels",
    description: "Ingress and response channel configuration returned by the tenant API.",
  },
  connectors: {
    eyebrow: "Boundary",
    title: "Connector Config",
    description: "Active connector configurations and governed config-change proposals.",
  },
  "action-policy": {
    eyebrow: "Governance",
    title: "Action Policy",
    description: "Action-tools policy editor — refund, warranty, replacement, and warehouse rules.",
  },
  "config-approvals": {
    eyebrow: "Governance",
    title: "Config Change Approvals",
    description: "Approve or reject proposed connector and action-policy changes (dual control).",
  },
  onboarding: {
    eyebrow: "Platform",
    title: "Tenant Onboarding",
    description: "Governed, state-driven onboarding from inert tenant to operational across the re-auth boundary.",
  },
  team: {
    eyebrow: "Identity",
    title: "Team & Roles",
    description: "Operator administration state and pending identity integration.",
  },
  audit: {
    eyebrow: "Audit",
    title: "Audit & Exports",
    description: "Operational alerts, exception records, and export-ready evidence.",
  },
  settings: {
    eyebrow: "Runtime",
    title: "Settings",
    description: "Client runtime, tenant scope, principal scope, and operator context.",
  },
};

interface DashboardActions {
  authSession: ReturnType<typeof useAuthSession>;
  openKnowledge: () => void;
  openTrace: (value: string, mode?: TraceLookup["mode"]) => void;
  selectedTraceLookup: TraceLookup | null;
}

const DashboardActionsContext = createContext<DashboardActions | null>(null);

export function useDashboardActions() {
  const context = useContext(DashboardActionsContext);
  if (!context) {
    throw new Error("useDashboardActions must be used inside DashboardShell");
  }
  return context;
}

function getActiveItem(pathname: string | null): DashboardViewId {
  const path = pathname ?? "";
  const match = Object.entries(dashboardRoutes).find(([, href]) => path === href);
  return (match?.[0] as DashboardViewId | undefined) ?? "operations";
}

export function DashboardShell({ children }: { children: ReactNode }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [selectedTraceLookup, setSelectedTraceLookup] = useState<TraceLookup | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [approvalCount, setApprovalCount] = useState<number | null>(null);
  const [crisisActive, setCrisisActive] = useState(false);
  const [fraudActive, setFraudActive] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const activeItem = getActiveItem(pathname);
  const authSession = useAuthSession();
  const operatorLabel = authSession.operatorLabel || getConfiguredOperatorLabel();
  const principalId = authSession.principal?.principal_id ?? getConfiguredPrincipalId();
  const tenantId = authSession.principal?.tenant_id ?? getConfiguredTenantId();
  const activeMeta = viewMeta[activeItem] ?? viewMeta.operations;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    document.body.style.overflow = mobileSidebarOpen ? "hidden" : "";
    document.documentElement.style.overflow = mobileSidebarOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
      document.documentElement.style.overflow = "";
    };
  }, [mobileSidebarOpen]);

  useEffect(() => {
    let active = true;

    const loadApprovalCount = () => {
      listActionApprovals({ status: "pending", limit: 100, offset: 0 })
        .then((approvals) => {
          if (active) setApprovalCount(approvals.length);
        })
        .catch(() => {
          if (active) setApprovalCount(null);
        });
    };

    loadApprovalCount();
    const interval = window.setInterval(loadApprovalCount, 30_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [tenantId]);

  useEffect(() => {
    let active = true;

    const loadFraudState = () => {
      listSemanticCircuitStates()
        .then((states) => {
          if (active) {
            setFraudActive(states.some((state) => state.state === "TRIPPED"));
          }
        })
        .catch(() => {
          if (active) setFraudActive(false);
        });
    };

    loadFraudState();
    const interval = window.setInterval(loadFraudState, 15_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [tenantId]);

  useEffect(() => {
    let active = true;

    const loadCrisisState = () => {
      listActiveCrisisDeployments()
        .then((deployments) => {
          if (active) setCrisisActive(deployments.length > 0);
        })
        .catch(() => {
          if (active) setCrisisActive(false);
        });
    };

    loadCrisisState();
    const interval = window.setInterval(loadCrisisState, 30_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [tenantId]);

  const navigateTo = (itemId: string) => {
    const href = dashboardRoutes[itemId as DashboardViewId];
    if (itemId === "trace") {
      setSelectedTraceLookup(null);
    }
    if (href) {
      router.push(href);
    }
    setMobileSidebarOpen(false);
  };

  const openTrace = (value: string, mode: TraceLookup["mode"] = "governance_decision_id") => {
    setSelectedTraceLookup({ value, mode });
    router.push(dashboardRoutes.trace);
    setMobileSidebarOpen(false);
  };

  const openKnowledge = () => {
    router.push(dashboardRoutes.knowledge);
    setMobileSidebarOpen(false);
  };

  return (
    <DashboardActionsContext.Provider
      value={{ authSession, openKnowledge, openTrace, selectedTraceLookup }}
    >
      <div className="min-h-screen bg-canvas lg:flex">
        {mobileSidebarOpen && (
          <button
            aria-label="Close navigation overlay"
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px] lg:hidden"
            onClick={() => setMobileSidebarOpen(false)}
          />
        )}

        <Sidebar
          collapsed={sidebarCollapsed}
          mobileOpen={mobileSidebarOpen}
          onMobileClose={() => setMobileSidebarOpen(false)}
          tenantName={tenantId ?? "Tenant scope not configured"}
          userName={operatorLabel}
          userRole={principalId ?? "Principal scope not configured"}
          onTenantClick={() => navigateTo("settings")}
          approvalCount={approvalCount}
          crisisActive={crisisActive}
          fraudActive={fraudActive}
          capabilities={authSession.principal?.capabilities ?? null}
        />

        <div className="min-w-0 flex-1 lg:flex lg:min-h-screen lg:flex-col">
          <header
            className={cn(
              "sticky top-0 z-30 border-b border-border-subtle",
              "bg-[color-mix(in_oklab,var(--surface)_92%,transparent)] backdrop-blur-md"
            )}
          >
            <div className="flex min-h-[56px] items-center justify-between gap-3 px-4 py-2.5 sm:px-6 lg:px-8">
              <div className="flex min-w-0 items-center gap-3">
                <button
                  type="button"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border-subtle bg-surface text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary lg:hidden"
                  onClick={() => setMobileSidebarOpen(true)}
                  aria-label="Open navigation"
                >
                  <Menu className="h-4 w-4" strokeWidth={1.8} />
                </button>
                <button
                  type="button"
                  className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border-subtle bg-surface text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary lg:flex"
                  onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
                  aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                >
                  {sidebarCollapsed ? (
                    <PanelLeftOpen className="h-3.5 w-3.5" strokeWidth={1.8} />
                  ) : (
                    <PanelLeftClose className="h-3.5 w-3.5" strokeWidth={1.8} />
                  )}
                </button>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 font-technical text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
                    <span>Command Center</span>
                    <span className="text-border-defined">/</span>
                    <span className="truncate text-gold-primary">{activeMeta.eyebrow}</span>
                  </div>
                  <h1 className="mt-0.5 truncate text-[15px] font-semibold tracking-[-0.005em] text-ink-primary sm:text-[16px]">
                    {activeMeta.title}
                  </h1>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-1.5">
                <button
                  type="button"
                  className="hidden h-8 items-center gap-2 rounded-md border border-border-subtle bg-surface px-2.5 font-technical text-[11px] uppercase tracking-[0.10em] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary sm:flex"
                  onClick={() => setCommandPaletteOpen(true)}
                >
                  <Command className="h-3 w-3" strokeWidth={1.8} />
                  <span>Command</span>
                  <span className="ml-1.5 rounded border border-border-subtle bg-surface-raised px-1.5 py-px text-[10px] text-ink-tertiary">
                    ⌘K
                  </span>
                </button>
                <button
                  type="button"
                  className={cn(
                    "flex h-9 items-center justify-center rounded-md border border-border-subtle bg-surface text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary",
                    "w-9 sm:h-8 sm:w-auto sm:gap-2 sm:px-2.5",
                    "focus-gold"
                  )}
                  onClick={() => navigateTo("settings")}
                  aria-label="Open operator settings"
                >
                  <UserCircle2 className="h-4 w-4 sm:h-3.5 sm:w-3.5" strokeWidth={1.8} />
                  <span className="hidden max-w-[180px] truncate text-[12px] font-medium text-ink-primary sm:block">
                    {operatorLabel}
                  </span>
                </button>
              </div>
            </div>
            {activeMeta.description && (
              <div className="hidden border-t border-border-subtle px-8 py-1.5 text-[11.5px] text-ink-secondary lg:block">
                {activeMeta.description}
              </div>
            )}
          </header>

          <div className="animate-cc-fade-in">{children}</div>
        </div>

        <CommandPalette
          isOpen={commandPaletteOpen}
          onClose={() => setCommandPaletteOpen(false)}
          onNavigate={navigateTo}
        />
      </div>
    </DashboardActionsContext.Provider>
  );
}
