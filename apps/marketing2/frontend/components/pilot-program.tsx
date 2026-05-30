import Link from "next/link";
import { ArrowRight } from "lucide-react";

const caseStudy = {
  client: "Global Consumer Electronics Manufacturer",
  category: "Hardware / Direct-to-Consumer Support",
  deploymentStart: "Q2 2026",
  channels: ["Email", "WhatsApp Business", "Voice"],
  languages: ["Arabic", "English", "Indonesian"],
  workflows: [
    "Warranty claim processing",
    "Replacement authorization",
    "Refund request handling",
    "Technical escalation routing",
    "Multilingual customer response",
  ],
  governanceOutcomes: [
    "Every warranty decision produces a governance record.",
    "Refunds above policy threshold require manager approval.",
    "Arabic language operations now covered — previously an unhandled gap in BPO operations.",
    "Complete audit trail delivered to compliance from Day 1.",
  ],
  deploymentTimeline: {
    "Week 1": "Operational policy mapping and configuration",
    "Week 2": "Channel integration — email, WhatsApp, voice",
    "Week 3": "Governance calibration and threshold tuning",
    "Week 4": "Full production launch",
  },
};

const overviewRows = [
  ["Client type", caseStudy.client],
  ["Channels", caseStudy.channels.join(" · ")],
  ["Languages", caseStudy.languages.join(" · ")],
  ["Deployment", "Week 1 policy mapping → Week 4 production"],
  ["Status", "Active"],
] as const;

export function PilotProgram() {
  return (
    <section className="bg-canvas px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
      <div className="mx-auto max-w-[1280px]">
        <p
          className="text-[10px] uppercase tracking-[0.18em] text-gold"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          Pilot program
        </p>
        <h2
          className="mt-5 max-w-[900px] text-[38px] font-bold leading-tight text-ink-primary sm:text-[54px]"
          style={{ fontFamily: "var(--font-cormorant-sc)" }}
        >
          Anonymized consumer electronics pilot. Full governance. Complete audit trail from Day 1.
        </h2>

        <div className="mt-10 grid gap-5 lg:grid-cols-2">
          <article className="rounded-md border border-border-subtle bg-white p-6">
            <p
              className="text-[10px] uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              Deployment overview
            </p>
            <div className="mt-5 grid gap-3">
              {overviewRows.map(([label, value]) => (
                <div
                  key={label}
                  className="grid gap-1 border-b border-border-subtle pb-3 last:border-b-0 last:pb-0 sm:grid-cols-[150px_1fr]"
                >
                  <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-tertiary">
                    {label}
                  </span>
                  <span className="text-[15px] leading-relaxed text-ink-body">{value}</span>
                </div>
              ))}
            </div>

            <div className="mt-6 rounded-md border border-border-subtle bg-surface-raised p-4">
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-gold">
                Deployment timeline
              </p>
              <ol className="mt-4 grid gap-3">
                {Object.entries(caseStudy.deploymentTimeline).map(([week, detail]) => (
                  <li key={week} className="grid gap-1 text-[14px] text-ink-body sm:grid-cols-[72px_1fr]">
                    <span className="font-semibold text-ink-primary">{week}</span>
                    <span>{detail}</span>
                  </li>
                ))}
              </ol>
              <Link
                href="/platform/implementation"
                className="mt-5 inline-flex items-center text-[13px] font-medium text-gold"
              >
                View implementation plan
                <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
              </Link>
            </div>
          </article>

          <article className="rounded-md border border-border-subtle bg-white p-6">
            <p
              className="text-[10px] uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              Governance outcomes
            </p>
            <ul className="mt-5 grid gap-3">
              {caseStudy.governanceOutcomes.map((outcome) => (
                <li key={outcome} className="flex gap-3 text-[15px] leading-relaxed text-ink-body">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
                  <span>{outcome}</span>
                </li>
              ))}
            </ul>
            <div className="mt-6 rounded-md border border-border-subtle bg-surface-raised p-4">
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-gold">
                Workflows
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {caseStudy.workflows.map((workflow) => (
                  <span
                    key={workflow}
                    className="rounded border border-border-subtle bg-white px-2.5 py-1.5 text-[12px] text-ink-body"
                  >
                    {workflow}
                  </span>
                ))}
              </div>
            </div>
          </article>
        </div>

        <div className="mt-6 rounded-md border border-[#C9A84C]/30 bg-[#C9A84C]/10 p-5 text-center">
          <p className="text-[15px] leading-relaxed text-ink-primary">
            Full case study available under NDA for qualified buyers.
          </p>
          <Link
            href="/company/contact?topic=Case%20Study%20Request"
            className="mt-5 inline-flex h-12 items-center justify-center rounded-md bg-[#05080F] px-6 text-[14px] font-semibold text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-ink-body"
          >
            Request case study
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}
