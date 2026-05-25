"use client";

import { useState, useEffect } from "react";
import {
  Command,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  UserCircle2,
} from "lucide-react";
import { Sidebar } from "@/components/sidebar";
import { OperationsQueue } from "@/components/operations-queue";
import { QueueStatusView } from "@/components/queue-status-view";
import { DlqInspectorView } from "@/components/dlq-inspector-view";
import { TraceInspector, type TraceLookup } from "@/components/trace-inspector";
import { CognitionHub } from "@/components/cognition-hub";
import { KnowledgeBase } from "@/components/knowledge-base";
import { CommandPalette } from "@/components/command-palette";
import {
  AuditExportsView,
  ChannelsView,
  GovernancePoliciesView,
  SettingsView,
  TeamRolesView,
  TopologyView,
} from "@/components/integration-views";
import {
  getConfiguredOperatorLabel,
  getConfiguredPrincipalId,
  getConfiguredTenantId,
} from "@/lib/api";
import { useAuthSession } from "@/lib/use-auth-session";
import { cn } from "@/lib/utils";

const viewMeta: Record<string, { eyebrow: string; title: string; description: string }> = {
  operations: {
    eyebrow: "Operations",
    title: "Operations Queue",
    description: "Live execution sessions, lifecycle state, latency, and governance outcomes.",
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
  trace: {
    eyebrow: "Observability",
    title: "Trace Inspector",
    description: "Replay recorded spans and inspect substrate-level execution evidence.",
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

export default function Home() {
  const [activeItem, setActiveItem] = useState("operations");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [selectedTraceLookup, setSelectedTraceLookup] = useState<TraceLookup | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
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

  const openTrace = (value: string, mode: TraceLookup["mode"] = "governance_decision_id") => {
    setSelectedTraceLookup({ value, mode });
    setActiveItem("trace");
    setMobileSidebarOpen(false);
  };

  const openKnowledge = () => {
    setActiveItem("knowledge");
    setMobileSidebarOpen(false);
  };

  const handleNavigate = (itemId: string) => {
    if (itemId === "trace") {
      setSelectedTraceLookup(null);
    }
    setActiveItem(itemId);
    setMobileSidebarOpen(false);
  };

  const renderActiveView = () => {
    switch (activeItem) {
      case "operations":
        return <OperationsQueue onOpenTrace={openTrace} />;
      case "queue-status":
        return <QueueStatusView />;
      case "dlq-inspector":
        return <DlqInspectorView />;
      case "trace":
        return (
          <TraceInspector
            key={selectedTraceLookup?.value ?? "manual-trace"}
            initialLookup={selectedTraceLookup}
          />
        );
      case "cognition":
        return <CognitionHub onOpenTrace={openTrace} onOpenKnowledge={openKnowledge} />;
      case "knowledge":
        return <KnowledgeBase />;
      case "governance":
        return <GovernancePoliciesView />;
      case "topology":
        return <TopologyView />;
      case "channels":
        return <ChannelsView />;
      case "team":
        return <TeamRolesView />;
      case "audit":
        return <AuditExportsView />;
      case "settings":
        return <SettingsView authSession={authSession} />;
      default:
        return <OperationsQueue onOpenTrace={openTrace} />;
    }
  };

  return (
    <div className="min-h-screen bg-canvas lg:flex">
      {mobileSidebarOpen && (
        <button
          aria-label="Close navigation overlay"
          className="fixed inset-0 z-40 bg-black/55 lg:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      <Sidebar
        activeItem={activeItem}
        collapsed={sidebarCollapsed}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
        onNavigate={handleNavigate}
        tenantName={tenantId ?? "Tenant scope not configured"}
        userName={operatorLabel}
        userRole={principalId ?? "Principal scope not configured"}
        onTenantClick={() => handleNavigate("settings")}
      />

      <div className="min-w-0 flex-1 lg:flex lg:min-h-screen lg:flex-col">
        <header className="sticky top-0 z-30 border-b border-border-subtle bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/88">
          <div className="flex min-h-[68px] items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded border border-border-subtle bg-surface-raised text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary lg:hidden"
                onClick={() => setMobileSidebarOpen(true)}
                aria-label="Open navigation"
              >
                <Menu className="h-5 w-5" strokeWidth={1.7} />
              </button>
              <button
                type="button"
                className="hidden h-9 w-9 shrink-0 items-center justify-center rounded border border-border-subtle bg-surface-raised text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary lg:flex"
                onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
                aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                {sidebarCollapsed ? (
                  <PanelLeftOpen className="h-4 w-4" strokeWidth={1.7} />
                ) : (
                  <PanelLeftClose className="h-4 w-4" strokeWidth={1.7} />
                )}
              </button>
              <div className="min-w-0">
                <div className="flex items-center gap-2 font-technical text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
                  <span>Command Center</span>
                  <span className="text-border-defined">/</span>
                  <span className="truncate text-gold-primary">{activeMeta.eyebrow}</span>
                </div>
                <h1 className="mt-1 truncate text-[18px] font-semibold text-ink-primary sm:text-[20px]">
                  {activeMeta.title}
                </h1>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                className="hidden h-9 items-center gap-2 rounded border border-border-subtle bg-surface-raised px-3 font-technical text-[11px] uppercase tracking-[0.12em] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary sm:flex"
                onClick={() => setCommandPaletteOpen(true)}
              >
                <Command className="h-3.5 w-3.5" strokeWidth={1.7} />
                Command
              </button>
              <button
                type="button"
                className={cn(
                  "flex h-11 w-11 items-center justify-center rounded border border-border-subtle bg-surface-raised text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary sm:h-9 sm:w-auto sm:gap-2 sm:px-3",
                  "focus-gold"
                )}
                onClick={() => handleNavigate("settings")}
                aria-label="Open operator settings"
              >
                <UserCircle2 className="h-5 w-5 sm:h-4 sm:w-4" strokeWidth={1.7} />
                <span className="hidden max-w-[170px] truncate text-[12px] font-medium text-ink-primary sm:block">
                  {operatorLabel}
                </span>
              </button>
            </div>
          </div>
          <div className="hidden border-t border-border-subtle px-8 py-2 text-[12px] text-ink-secondary lg:block">
            {activeMeta.description}
          </div>
        </header>

        {renderActiveView()}
      </div>

      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={handleNavigate}
      />
    </div>
  );
}
