"use client";

import { TraceInspector } from "@/components/trace-inspector";
import { useDashboardActions } from "@/components/dashboard-shell";

export default function DashboardTracesPage() {
  const { selectedTraceLookup } = useDashboardActions();
  return (
    <TraceInspector
      key={selectedTraceLookup?.value ?? "manual-trace"}
      initialLookup={selectedTraceLookup}
    />
  );
}
