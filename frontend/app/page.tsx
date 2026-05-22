"use client";

import { useState } from "react";
import { Sidebar } from "@/components/sidebar";

export default function Home() {
  const [activeItem, setActiveItem] = useState("operations");

  return (
    <div className="flex min-h-screen bg-canvas">
      <Sidebar
        activeItem={activeItem}
        onNavigate={setActiveItem}
        tenantName="Acme Corporation"
        userName="Sarah Chen"
        userRole="Operator"
      />

      {/* Main content area placeholder */}
      <main className="flex-1 p-8">
        <div className="max-w-4xl">
          <h1 className="font-display text-[32px] font-semibold text-ink-primary mb-2">
            Command Center
          </h1>
          <p className="text-ink-body text-[15px] leading-relaxed mb-8">
            Deterministic multi-agent operating system for enterprise governed
            execution infrastructure.
          </p>

          {/* Active section indicator */}
          <div className="p-6 bg-surface rounded-lg border border-border-subtle">
            <p className="eyebrow text-ink-tertiary mb-2">Current View</p>
            <p className="text-[18px] font-medium text-ink-primary capitalize">
              {activeItem.replace("-", " ")}
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
