import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

export const metadata: Metadata = {
  title: "Implementation Plan - Operious AI",
  description:
    "The Operious 30-day implementation plan from architecture review through governed production launch.",
};

const phases = [
  {
    label: "Phase 1",
    title: "Architecture Review",
    days: "Days 1-3",
    body:
      "Solutions architect reviews your current operational stack, identifies target workflows, maps channel integrations, and defines governance policy requirements.",
    deliverable: "Technical scope document and integration plan.",
  },
  {
    label: "Phase 2",
    title: "Policy Configuration",
    days: "Days 4-10",
    body:
      "Governance policies configured for your workflows. Threshold calibration for automated vs. approval-required actions. Channel connections tested against staging.",
    deliverable: "Configured governance environment.",
  },
  {
    label: "Phase 3",
    title: "Integration and Testing",
    days: "Days 11-20",
    body:
      "Channel adapters connected. Inbound routing verified. Outbound dispatch tested. End-to-end governance traces reviewed with your operations team.",
    deliverable: "Integration-complete staging environment.",
  },
  {
    label: "Phase 4",
    title: "Production Launch",
    days: "Days 21-30",
    body:
      "Full production deployment. Live governance enforcement. Audit trail active from first contact. Operations team briefed on Command Center and approval workflow.",
    deliverable: "Production system with live audit trail.",
  },
] as const;

const postLaunch = [
  "Ongoing governance policy tuning.",
  "Weekly operational review during pilot.",
  "Audit export available on demand.",
  "Architecture review available for any new workflow.",
];

export default function ImplementationPage() {
  return (
    <main className="flex-1 overflow-x-hidden">
      <section className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16 lg:pb-24">
        <div className="mx-auto max-w-[1120px]">
          <p
            className="text-[10px] uppercase tracking-[0.18em] text-gold"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            Platform / Implementation
          </p>
          <h1
            className="mt-5 max-w-[900px] text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            From architecture review to production in 30 days.
          </h1>
        </div>
      </section>

      <section className="bg-surface-raised px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto grid max-w-[1280px] gap-5 lg:grid-cols-4">
          {phases.map((phase, index) => (
            <article
              key={phase.label}
              className="relative rounded-md border border-border-subtle bg-white p-6"
            >
              <div className="flex items-center justify-between gap-4">
                <span className="flex h-9 w-9 items-center justify-center rounded-md bg-ink-primary font-mono text-[11px] text-gold-bright">
                  {index + 1}
                </span>
                <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-tertiary">
                  {phase.days}
                </span>
              </div>
              <p
                className="mt-5 text-[10px] uppercase tracking-[0.18em] text-gold"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                {phase.label}
              </p>
              <h2
                className="mt-3 text-[26px] font-semibold leading-tight text-ink-primary"
                style={{ fontFamily: "var(--font-cormorant-sc)" }}
              >
                {phase.title}
              </h2>
              <p className="mt-4 text-[15px] leading-relaxed text-ink-body">{phase.body}</p>
              <p className="mt-5 border-t border-border-subtle pt-4 text-[14px] leading-relaxed text-ink-secondary">
                <span className="font-semibold text-ink-primary">Deliverable:</span>{" "}
                {phase.deliverable}
              </p>
            </article>
          ))}
        </div>

        <div className="mx-auto mt-8 max-w-[1120px] rounded-md border border-border-subtle bg-white p-6">
          <p
            className="text-[10px] uppercase tracking-[0.18em] text-gold"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            Post-launch
          </p>
          <ul className="mt-5 grid gap-3 md:grid-cols-2">
            {postLaunch.map((item) => (
              <li key={item} className="flex gap-3 text-[15px] leading-relaxed text-ink-body">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="bg-canvas px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto max-w-[1120px]">
          <Link
            href="/company/contact?topic=Architecture%20Review"
            className="inline-flex h-12 items-center justify-center rounded-md bg-ink-primary px-5 text-[14px] font-semibold text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-ink-body"
          >
            Book an Architecture Review
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </section>
    </main>
  );
}
