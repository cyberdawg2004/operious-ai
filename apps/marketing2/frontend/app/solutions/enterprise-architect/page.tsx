import type { Metadata } from "next";
import { SolutionPage } from "../_components/solution-page";

export const metadata: Metadata = {
  title: "For Enterprise Architects - Operious AI",
  description:
    "Operious architecture details for tenancy, deterministic identity, integrations, and governance failure modes.",
};

export default function EnterpriseArchitectSolutionPage() {
  return (
    <SolutionPage
      eyebrow="Solutions / Enterprise Architect"
      title="Seven substrates. Row-level security. Deterministic identity. Defensible at every layer."
      intro="Read the full platform architecture for the complete model."
      concerns={[
        {
          label: "Tenancy",
          body:
            "Mandatory Postgres RLS with FORCE enforcement. No cross-tenant data access possible at the DB layer.",
        },
        {
          label: "Identity",
          body:
            "UUID5 deterministic identity throughout. Every decision, agent, and execution cryptographically fingerprinted. Fully replayable.",
        },
        {
          label: "Integration",
          body:
            "REST API. Webhook receivers. Outbound governed dispatch. Event fabric with append-only records.",
          href: "/platform",
        },
        {
          label: "Failure modes",
          body:
            "Governance fail-closed by default. Empty policy chains return DENY. No action executes on governance failure.",
        },
      ]}
      ctaLabel="Request architecture documentation"
      ctaHref="/company/contact?topic=Architecture%20Documentation"
    />
  );
}
