"use client";

import { CognitionHub } from "@/components/cognition-hub";
import { useDashboardActions } from "@/components/dashboard-shell";

export default function DashboardCognitionPage() {
  const { openKnowledge, openTrace } = useDashboardActions();
  return <CognitionHub onOpenTrace={openTrace} onOpenKnowledge={openKnowledge} />;
}
