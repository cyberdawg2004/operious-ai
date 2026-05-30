import type { Metadata } from "next";
import { SolutionPage } from "../_components/solution-page";

export const metadata: Metadata = {
  title: "For COOs - Operious AI",
  description:
    "How Operious gives COOs predictable cost, accountable AI operations, and board-ready audit evidence.",
};

export default function CooSolutionPage() {
  return (
    <SolutionPage
      eyebrow="Solutions / COO"
      title="Give your COO accountability over AI operations she can actually show the board."
      concerns={[
        {
          label: "Operational cost",
          body:
            "AI-coordinated Tier 1 and Tier 2 operations at a fraction of BPO cost. Cost is fixed and predictable regardless of contact volume growth. No headcount scaling required for volume increases.",
        },
        {
          label: "Accountability",
          body:
            "Every operational decision produces a permanent record. Your COO can produce a complete audit export for any workflow, any time period, any contact type - without requesting it from an engineering team.",
        },
        {
          label: "Implementation",
          body:
            "30-day deployment timeline. Policy configuration in week one. Production in week four. Operations team trained on the Command Center before go-live.",
        },
      ]}
      ctaLabel="Book a COO briefing"
      ctaHref="/company/contact?topic=COO%20Briefing"
    />
  );
}
