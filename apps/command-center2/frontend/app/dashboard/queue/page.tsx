"use client";

import { OperationsQueue } from "@/components/operations-queue";
import { useDashboardActions } from "@/components/dashboard-shell";

export default function DashboardQueuePage() {
  const { openTrace } = useDashboardActions();
  return <OperationsQueue onOpenTrace={openTrace} />;
}
