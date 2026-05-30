import type { Metadata } from "next";
import { SolutionPage } from "../_components/solution-page";

export const metadata: Metadata = {
  title: "For CIOs - Operious AI",
  description:
    "Vendor maturity, security posture, deployment model, and procurement answers for CIO review.",
};

export default function CioSolutionPage() {
  return (
    <SolutionPage
      eyebrow="Solutions / CIO"
      title="Vendor maturity, security posture, and deployment model - answered before procurement."
      concerns={[
        {
          label: "Security",
          body:
            "Data architecture, encryption posture, access control, compliance status, and operational security are documented for enterprise review.",
          href: "/trust/security",
        },
        {
          label: "Compliance",
          body: "SOC 2 Type II in progress, Q3 2026.",
        },
        {
          label: "Deployment",
          body: "Enterprise SaaS. VPC available.",
        },
        {
          label: "Contracts",
          body: "DPA available. BAA available for healthcare.",
        },
      ]}
      ctaLabel="Request security packet and procurement kit"
      ctaHref="/company/contact?topic=Security%20Packet%20and%20Procurement%20Kit"
    />
  );
}
