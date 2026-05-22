"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "@/components/sidebar";
import { OperationsQueue } from "@/components/operations-queue";
import { TraceInspector } from "@/components/trace-inspector";
import { CognitionHub } from "@/components/cognition-hub";
import { KnowledgeBase } from "@/components/knowledge-base";
import { CommandPalette } from "@/components/command-palette";

export default function Home() {
  const [activeItem, setActiveItem] = useState("operations");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  // Global keyboard shortcut for command palette
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

  return (
    <div className="flex min-h-screen bg-canvas">
      <Sidebar
        activeItem={activeItem}
        onNavigate={setActiveItem}
        tenantName="Acme Corporation"
        userName="Sarah Chen"
        userRole="Operator"
      />

      {/* Main content area - render based on active nav item */}
      {activeItem === "operations" ? (
        <OperationsQueue />
      ) : activeItem === "trace" ? (
        <TraceInspector />
      ) : activeItem === "cognition" ? (
        <CognitionHub />
      ) : activeItem === "knowledge" ? (
        <KnowledgeBase />
      ) : (
        <main className="flex-1 p-8 bg-canvas">
          <div className="max-w-4xl">
            <h1 className="font-display text-[32px] font-semibold text-ink-primary mb-2">
              {activeItem.split("-").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ")}
            </h1>
            <p className="text-ink-body text-[15px] leading-relaxed mb-8">
              This view is coming soon.
            </p>
          </div>
        </main>
      )}

      {/* Command Palette */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={(route) => setActiveItem(route)}
      />
    </div>
  );
}
