import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

export const metadata: Metadata = {
  title: "Security Architecture and Trust Overview - Operious AI",
  description:
    "Operious security packet covering data architecture, encryption, access control, compliance posture, and operational security.",
};

const dataArchitecture = [
  {
    label: "Data isolation",
    body:
      "All customer operational data is isolated at the database row level using Postgres Row Level Security with FORCE enforcement. No application-layer query can access another tenant's data regardless of what an AI model instructs.",
  },
  {
    label: "Data retention",
    body:
      "Operational records, governance decisions, session timelines, and audit events are retained for the duration of your contract plus 90 days, unless a shorter retention period is agreed in your DPA. Deletion requests are honored within 30 days.",
  },
  {
    label: "Data processing",
    body:
      "Operious processes customer contact data for the sole purpose of executing governed operational workflows. Customer data is never used for model training. Customer data is never shared across tenants.",
  },
  {
    label: "Data residency",
    body:
      "Default deployment: AWS ap-southeast-1 (Singapore) for APAC clients. Regional deployment options available for EU and US requirements. VPC and private deployment available under enterprise agreement.",
  },
];

const encryptionRows = [
  {
    label: "At rest",
    body:
      "All tenant data encrypted at rest using AES-256-GCM. Tenant channel credentials - API keys, webhook secrets, access tokens - are encrypted with tenant-specific keys. Credentials are never returned in API responses.",
  },
  {
    label: "In transit",
    body:
      "All client-server communication over TLS 1.3. Internal service communication encrypted in transit. No plaintext credential transmission at any layer.",
  },
  {
    label: "Audit trail integrity",
    body:
      "Every governance decision is signed with HMAC-SHA256. Every session event carries a UUID5 deterministic identity. Audit records are append-only by architecture - no record can be modified after creation, at the application or database layer.",
  },
];

const accessRows = [
  {
    label: "Tenant isolation",
    body:
      "Each enterprise client is a separate tenant. Tenant boundaries are enforced at the database layer with mandatory Row Level Security. No operator can access tenant data through application interfaces.",
  },
  {
    label: "Role-based access",
    body:
      "Role-based access control enforced via Auth0. Operator, supervisor, manager, and analyst roles available. Role permissions are configurable per tenant.",
  },
  {
    label: "SSO",
    body:
      "SSO integration available for enterprise clients. SAML 2.0 and OIDC supported. SCIM provisioning available on request.",
  },
];

const complianceRows = [
  {
    label: "SOC 2 Type II",
    body:
      "Audit planning in progress. Target: Q3 2026. Operious does not present in-progress certifications as completed. Pre-SOC 2 architecture review and security questionnaire responses available upon request.",
  },
  {
    label: "HIPAA",
    body:
      "Business Associate Agreement available for healthcare clients where deployment scope and controls are reviewed and agreed.",
  },
  {
    label: "GDPR / Privacy",
    body:
      "Data Processing Addendum available on request. Subprocessor list maintained and available to enterprise clients. Data subject request handling supported.",
  },
];

const operationalControls = [
  {
    label: "Vulnerability disclosure",
    body:
      "Security disclosures accepted at security@operious.com. Response within 24 hours for critical reports.",
  },
  {
    label: "Incident response",
    body:
      "Security incident notification within 72 hours of confirmed breach affecting tenant data, per applicable regulatory requirements.",
  },
  {
    label: "Penetration testing",
    body:
      "Third-party penetration testing planned for Q3 2026 alongside SOC 2 audit. Results shared with enterprise clients under NDA.",
  },
  {
    label: "Dependency management",
    body:
      "Software dependencies audited continuously. Zero CVE-affecting dependencies in production stack.",
  },
];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="text-[10px] uppercase tracking-[0.18em] text-gold"
      style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
    >
      {children}
    </p>
  );
}

function DetailRows({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; body: string }[];
}) {
  return (
    <section className="border-t border-border-subtle pt-8">
      <h2
        className="text-[34px] font-bold leading-tight text-ink-primary sm:text-[44px]"
        style={{ fontFamily: "var(--font-cormorant-sc)" }}
      >
        {title}
      </h2>
      <div className="mt-8 grid gap-4">
        {rows.map((row) => (
          <article
            key={row.label}
            className="grid gap-3 rounded-md border border-border-subtle bg-white p-5 md:grid-cols-[220px_1fr]"
          >
            <h3
              className="text-[11px] uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              {row.label}
            </h3>
            <p className="text-[15px] leading-relaxed text-ink-body">{row.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export default function SecurityOverviewPage() {
  return (
    <main className="flex-1 overflow-x-hidden">
      <section className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16 lg:pb-24">
        <div className="mx-auto max-w-[1120px]">
          <SectionLabel>Trust / Security Packet</SectionLabel>
          <h1
            className="mt-5 max-w-[920px] text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Security Architecture and Trust Overview
          </h1>
          <p className="mt-6 max-w-[820px] text-[18px] leading-relaxed text-ink-secondary sm:text-[20px]">
            This packet summarizes the data architecture, encryption posture,
            access model, compliance status, and operational controls available
            for enterprise security and procurement review.
          </p>
        </div>
      </section>

      <section className="bg-surface-raised px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto grid max-w-[1120px] gap-12">
          <DetailRows title="How Operious handles your data" rows={dataArchitecture} />
          <DetailRows title="Encryption posture" rows={encryptionRows} />
          <DetailRows title="Identity and access model" rows={accessRows} />
          <DetailRows title="Compliance and certifications" rows={complianceRows} />

          <section className="border-t border-border-subtle pt-8">
            <h2
              className="text-[34px] font-bold leading-tight text-ink-primary sm:text-[44px]"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              Operational controls
            </h2>
            <div className="mt-8 grid gap-4 md:grid-cols-2">
              {operationalControls.map((control) => (
                <article
                  key={control.label}
                  className="rounded-md border border-border-subtle bg-white p-5"
                >
                  <h3
                    className="text-[11px] uppercase tracking-[0.18em] text-gold"
                    style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
                  >
                    {control.label}
                  </h3>
                  <p className="mt-4 text-[15px] leading-relaxed text-ink-body">
                    {control.body}
                  </p>
                </article>
              ))}
            </div>
          </section>
        </div>
      </section>

      <section className="bg-canvas px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto max-w-[1120px] rounded-md border border-border-subtle bg-white p-6">
          <p className="max-w-[760px] text-[16px] leading-relaxed text-ink-body">
            For a complete security review packet including data flow diagrams,
            identity model, tenancy architecture, and security questionnaire
            responses, request a security review.
          </p>
          <Link
            href="/company/contact?subject=Security%20Review%20Request"
            className="mt-6 inline-flex h-12 items-center justify-center rounded-md bg-ink-primary px-5 text-[14px] font-semibold text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-ink-body"
          >
            Request Security Review
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </section>
    </main>
  );
}
