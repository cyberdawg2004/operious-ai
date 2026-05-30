import type { Metadata } from "next";
import { SolutionPage } from "../_components/solution-page";

export const metadata: Metadata = {
  title: "For Compliance and Legal - Operious AI",
  description:
    "How Operious provides audit trail, exportable evidence, and compliance documentation for governed AI operations.",
};

export default function ComplianceSolutionPage() {
  return (
    <SolutionPage
      eyebrow="Solutions / Compliance and Legal"
      title="Audit trail by architecture. Evidence on demand. No reconstruction required."
      concerns={[
        {
          label: "Audit trail",
          body:
            "Every governance decision produces a structured, append-only, HMAC-signed record at the moment of creation. Your auditors get structured evidence, not reconstructed logs.",
        },
        {
          label: "Export",
          body:
            "Audit export available on demand. Complete governance decision history, session events, policy versions in effect, and action records exportable in structured format.",
        },
        {
          label: "Regulatory",
          body:
            "GDPR DPA available. HIPAA BAA available. SOC 2 Type II in progress. Incident notification within 72 hours of confirmed breach.",
        },
      ]}
      ctaLabel="Request compliance documentation"
      ctaHref="/company/contact?topic=Compliance%20Documentation"
    />
  );
}
