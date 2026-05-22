"use client";

import { useState } from "react";
import { Sidebar } from "@/components/sidebar";
import { OperationsQueue } from "@/components/operations-queue";
import { TraceInspector } from "@/components/trace-inspector";

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

      {/* Main content area - render based on active nav item */}
      {activeItem === "operations" ? (
        <OperationsQueue />
      ) : activeItem === "trace" ? (
        <TraceInspector />
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
    </div>
  );
}
