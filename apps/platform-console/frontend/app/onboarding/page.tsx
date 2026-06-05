"use client";

import { PlatformConsole } from "@/components/platform-console";
import { TenantOnboarding } from "@/components/tenant-onboarding";

export default function OnboardingPage() {
  return (
    <PlatformConsole>
      <TenantOnboarding />
    </PlatformConsole>
  );
}
