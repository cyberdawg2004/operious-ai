"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "@/components/sidebar";
import { OperationsQueue } from "@/components/operations-queue";
import { TraceInspector } from "@/components/trace-inspector";
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

export default function Home() {
  const [activeItem, setActiveItem] = useState("operations");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);

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

  const openTrace = (traceId: string) => {
    setSelectedTraceId(traceId);
    setActiveItem("trace");
  };

  const openKnowledge = () => {
    setActiveItem("knowledge");
  };

  const renderActiveView = () => {
    switch (activeItem) {
      case "operations":
        return <OperationsQueue onOpenTrace={openTrace} />;
      case "trace":
        return (
          <TraceInspector
            key={selectedTraceId ?? "manual-trace"}
            initialTraceId={selectedTraceId}
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
        return <SettingsView />;
      default:
        return <OperationsQueue onOpenTrace={openTrace} />;
    }
  };

  return (
    <div className="flex min-h-screen bg-canvas">
      <Sidebar
        activeItem={activeItem}
        onNavigate={setActiveItem}
        tenantName={getConfiguredTenantId() ?? "Tenant scope not configured"}
        userName={getConfiguredOperatorLabel()}
        userRole={getConfiguredPrincipalId() ?? "Principal scope not configured"}
        onTenantClick={() => setActiveItem("settings")}
      />

      {renderActiveView()}

      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={(route) => {
          if (route === "trace") {
            setSelectedTraceId(null);
          }
          setActiveItem(route);
        }}
      />
    </div>
  );
}
