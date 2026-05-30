import type { Metadata } from "next";
import { SolutionPage } from "../_components/solution-page";

export const metadata: Metadata = {
  title: "For VP Support - Operious AI",
  description:
    "How Operious helps support leaders reduce escalations, close language gaps, and prove every AI-assisted decision.",
};

export default function VpSupportSolutionPage() {
  return (
    <SolutionPage
      eyebrow="Solutions / VP Support"
      title="Reduce escalations. Close the language gap. Prove every decision to your compliance team."
      concerns={[
        {
          label: "Workflow integration",
          body:
            "Operious connects alongside your existing helpdesk. No Zendesk migration. Your team keeps their tooling. Operious adds governance to what your AI agents do before they act on your customers.",
        },
        {
          label: "Quality",
          body:
            "Every contact classified with confidence scoring. Contacts below confidence threshold escalated to your team with full context - classification, evidence, governance reason - before they read the message.",
        },
        {
          label: "Language",
          body:
            "Arabic, English, Indonesian, Spanish, French, and Chinese handled natively. Language detected, processed, responded to, and translated back - all within the same governed pipeline.",
        },
      ]}
      ctaLabel="Book a support operations review"
      ctaHref="/company/contact?topic=Support%20Operations%20Review"
    />
  );
}
