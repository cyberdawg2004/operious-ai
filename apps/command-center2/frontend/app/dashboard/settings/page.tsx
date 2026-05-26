"use client";

import { SettingsView } from "@/components/integration-views";
import { useDashboardActions } from "@/components/dashboard-shell";

export default function DashboardSettingsPage() {
  const { authSession } = useDashboardActions();
  return <SettingsView authSession={authSession} />;
}
