import Link from "next/link";
import {
  ArrowRight,
  Cpu,
  FileSearch,
  Landmark,
  Network,
  RadioTower,
  Scale,
  ShieldCheck,
  Stethoscope,
  Truck,
} from "lucide-react";
import { KernelSeal } from "@/components/kernel-seal";

const pillars = [
  {
    title: "Constitutional Governance",
    body: "Policies execute, not suggest. Decisions cannot bypass the governance layer.",
    href: "/platform/governance",
    icon: Scale,
  },
  {
    title: "Reconstructible Truth",
    body: "Replay any operational decision at any point in time with cryptographic certainty.",
    href: "/platform/replay",
    icon: FileSearch,
  },
  {
    title: "Multi-Agent Coordination",
    body: "Deterministic agent orchestration with structural guarantees against deadlock and conflict.",
    href: "/platform/agents",
    icon: Network,
  },
];

const industries = [
  {
    title: "Hardware",
    href: "/industries/hardware",
    icon: Cpu,
    body: "Warranty, returns, charging issues, defect categorization, and multilingual support.",
  },
  {
    title: "Financial services",
    href: "/industries/financial-services",
    icon: Landmark,
    body: "Disputes, fraud-adjacent triage, regulatory evidence, and governed communications.",
  },
  {
    title: "Healthcare",
    href: "/industries/healthcare",
    icon: Stethoscope,
    body: "PHI-aware intake, patient communication, eligibility support, and escalation.",
  },
  {
    title: "Insurance",
    href: "/industries/insurance",
    icon: ShieldCheck,
    body: "Claims triage, FNOL handling, policy questions, and adjuster review boundaries.",
  },
  {
    title: "Telecom",
    href: "/industries/telecom",
    icon: RadioTower,
    body: "Service interruption, billing disputes, SIM flows, and device provisioning.",
  },
  {
    title: "Logistics",
    href: "/industries/logistics",
    icon: Truck,
    body: "Shipment exceptions, cross-border documentation, and delivery dispute resolution.",
  },
];

const architectureLayers = [
  "Boundary",
  "Coordination",
  "Governance",
  "Session",
  "Execution",
  "Supervisor",
  "Arbitration",
];

const trustCards = [
  {
    title: "SOC 2 Type II",
    meta: "In progress",
    body: "Audit planning is targeted for Q3 2026. Operious does not present roadmap attestations as completed certifications.",
  },
  {
    title: "HIPAA BAA",
    meta: "Available",
    body: "Business Associate Agreement support is available for healthcare clients where deployment scope and controls are agreed.",
  },
  {
    title: "Tenant isolation",
    meta: "End-to-end",
    body: "Policies, credentials, knowledge, operational events, and projected state are designed to remain tenant-scoped.",
  },
];

const featuredArticles = [
  {
    title: "Constitutional AI governance requires runtime enforcement",
    href: "/insights/constitutional-ai-governance",
    body: "Why policy-as-prompt fails the enterprise audit test and how admission tokens change the control plane.",
  },
  {
    title: "Reconstructible truth is the missing audit primitive",
    href: "/insights/reconstructible-truth",
    body: "How deterministic identity and event fabrics make AI operations defensible after the fact.",
  },
  {
    title: "Beyond LLM wrappers",
    href: "/insights/beyond-llm-wrappers",
    body: "The seven substrates that separate governed execution infrastructure from model orchestration.",
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

export default function Home() {
  return (
    <main className="flex-1">
      <section className="relative bg-[#05080F] px-4 pb-20 pt-32 text-[#D8E4F4] sm:px-8 sm:pb-24 sm:pt-36 lg:px-16">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.05]"
          style={{
            backgroundImage:
              "linear-gradient(#D8E4F4 1px, transparent 1px), linear-gradient(90deg, #D8E4F4 1px, transparent 1px)",
            backgroundSize: "56px 56px",
          }}
        />
        <div className="relative mx-auto grid max-w-[1280px] gap-12 lg:grid-cols-[0.8fr_1.2fr] lg:items-center">
          <div className="flex justify-center lg:justify-start">
            <KernelSeal size={260} phase={3} />
          </div>
          <div>
            <SectionLabel>Operious AI</SectionLabel>
            <h1
              className="mt-6 max-w-[860px] text-[44px] font-bold leading-[1.04] sm:text-[62px] lg:text-[82px]"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              Governed execution infrastructure for regulated enterprise operations.
            </h1>
            <p className="mt-7 max-w-[760px] text-[18px] leading-relaxed text-[#9FB0CA] sm:text-[21px]">
              Operious is a deterministic multi-agent system that runs Tier 1 and Tier 2
              operational workflows with forensic auditability. Every decision is governed.
              Every action is reconstructible. Every byte of state is tenant-isolated.
            </p>
            <div className="mt-10 flex flex-col gap-3 sm:flex-row">
              <Link
                href="/company/contact"
                className="inline-flex h-12 items-center justify-center rounded-md bg-[#C9A84C] px-6 text-[14px] font-semibold text-[#05080F] transition-colors hover:bg-[#D4B85A]"
              >
                Request enterprise access
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
              <Link
                href="/platform"
                className="inline-flex h-12 items-center justify-center rounded-md border border-[#1A2744] px-6 text-[14px] font-semibold text-[#D8E4F4] transition-colors hover:border-[#C9A84C] hover:text-[#C9A84C]"
              >
                Read the architecture
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="bg-canvas px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto grid max-w-[1280px] gap-6 lg:grid-cols-3">
          {pillars.map((pillar) => {
            const Icon = pillar.icon;
            return (
              <Link
                key={pillar.href}
                href={pillar.href}
                className="group rounded-md border border-border-subtle bg-white p-7 transition-shadow hover:shadow-[var(--shadow-card-hover)]"
              >
                <Icon className="h-8 w-8 text-gold" />
                <h2
                  className="mt-6 text-[26px] font-semibold text-ink-primary"
                  style={{ fontFamily: "var(--font-cormorant-sc)" }}
                >
                  {pillar.title}
                </h2>
                <p className="mt-3 text-[15px] leading-relaxed text-ink-body">{pillar.body}</p>
                <span className="mt-6 inline-flex items-center text-[13px] font-medium text-gold">
                  Open pillar
                  <ArrowRight className="ml-1.5 h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                </span>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="bg-surface-raised px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
        <div className="mx-auto max-w-[1280px]">
          <SectionLabel>Industries</SectionLabel>
          <div className="mt-5 grid gap-6 lg:grid-cols-[0.72fr_1.28fr] lg:items-end">
            <h2
              className="text-[38px] font-bold leading-tight text-ink-primary sm:text-[54px]"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              Built for operationally regulated environments.
            </h2>
            <p className="text-[16px] leading-relaxed text-ink-body">
              Operious deploys where operational work must be fast, multilingual, governed,
              and reconstructible. Each card below links to a domain-specific use case.
            </p>
          </div>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {industries.map((industry) => {
              const Icon = industry.icon;
              return (
                <Link
                  key={industry.href}
                  href={industry.href}
                  className="group rounded-md border border-border-subtle bg-white p-6 transition-shadow hover:shadow-[var(--shadow-card-hover)]"
                >
                  <div className="flex h-12 w-12 items-center justify-center rounded-md border border-border-subtle bg-surface-raised">
                    <Icon className="h-6 w-6 text-gold" />
                  </div>
                  <h3
                    className="mt-5 text-[24px] font-semibold text-ink-primary"
                    style={{ fontFamily: "var(--font-cormorant-sc)" }}
                  >
                    {industry.title}
                  </h3>
                  <p className="mt-2 text-[14px] leading-relaxed text-ink-body">
                    {industry.body}
                  </p>
                  <span className="mt-5 inline-flex items-center text-[13px] font-medium text-gold">
                    View use case
                    <ArrowRight className="ml-1.5 h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      <section className="bg-[#05080F] px-4 py-20 text-[#D8E4F4] sm:px-8 sm:py-24 lg:px-16">
        <div className="mx-auto grid max-w-[1280px] gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
          <div>
            <SectionLabel>Architecture</SectionLabel>
            <h2
              className="mt-5 text-[38px] font-bold leading-tight sm:text-[54px]"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              A substrate diagram for governed execution.
            </h2>
            <p className="mt-6 text-[16px] leading-relaxed text-[#9FB0CA]">
              Operious does not place a chatbot over an enterprise queue. The runtime
              separates authority into seven substrates so tenant boundaries, agent
              coordination, policy admission, execution, supervision, and conflict
              handling can be inspected independently.
            </p>
            <Link
              href="/platform"
              className="mt-8 inline-flex h-12 items-center justify-center rounded-md bg-[#C9A84C] px-5 text-[14px] font-semibold text-[#05080F] transition-colors hover:bg-[#D4B85A]"
            >
              Explore platform architecture
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </div>
          <div className="rounded-md border border-[#1A2744] bg-[#0B1120] p-5">
            <div className="grid gap-3">
              {architectureLayers.map((layer, index) => (
                <div
                  key={layer}
                  className="flex items-center justify-between rounded-md border border-[#1A2744] bg-[#05080F] px-5 py-4"
                >
                  <span
                    className="text-[12px] uppercase tracking-[0.16em] text-[#C9A84C]"
                    style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="text-[16px] font-medium">{layer}</span>
                </div>
              ))}
            </div>
            <p
              className="mt-5 text-[12px] uppercase tracking-[0.16em] text-[#7A90B4]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              Boundary -&gt; Coordination -&gt; Governance -&gt; Session -&gt; Execution -&gt;
              Supervisor -&gt; Arbitration
            </p>
          </div>
        </div>
      </section>

      <section className="bg-canvas px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
        <div className="mx-auto max-w-[1280px]">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <SectionLabel>Trust</SectionLabel>
              <h2
                className="mt-5 max-w-[780px] text-[38px] font-bold leading-tight text-ink-primary sm:text-[54px]"
                style={{ fontFamily: "var(--font-cormorant-sc)" }}
              >
                Trust posture stated plainly.
              </h2>
            </div>
            <Link href="/trust" className="inline-flex items-center text-[14px] font-medium text-gold">
              Open trust center
              <ArrowRight className="ml-1.5 h-4 w-4" />
            </Link>
          </div>
          <div className="mt-10 grid gap-5 lg:grid-cols-3">
            {trustCards.map((card) => (
              <article key={card.title} className="rounded-md border border-border-subtle bg-white p-6">
                <p
                  className="text-[10px] uppercase tracking-[0.18em] text-gold"
                  style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
                >
                  {card.meta}
                </p>
                <h3
                  className="mt-4 text-[24px] font-semibold text-ink-primary"
                  style={{ fontFamily: "var(--font-cormorant-sc)" }}
                >
                  {card.title}
                </h3>
                <p className="mt-3 text-[15px] leading-relaxed text-ink-body">{card.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-surface-raised px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
        <div className="mx-auto max-w-[1280px]">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <SectionLabel>Insights</SectionLabel>
              <h2
                className="mt-5 max-w-[780px] text-[38px] font-bold leading-tight text-ink-primary sm:text-[54px]"
                style={{ fontFamily: "var(--font-cormorant-sc)" }}
              >
                Architecture writing for enterprise AI buyers.
              </h2>
            </div>
            <Link href="/insights" className="inline-flex items-center text-[14px] font-medium text-gold">
              View all insights
              <ArrowRight className="ml-1.5 h-4 w-4" />
            </Link>
          </div>
          <div className="mt-10 grid gap-5 lg:grid-cols-3">
            {featuredArticles.map((article) => (
              <Link
                key={article.href}
                href={article.href}
                className="group rounded-md border border-border-subtle bg-white p-6 transition-shadow hover:shadow-[var(--shadow-card-hover)]"
              >
                <h3
                  className="text-[24px] font-semibold leading-tight text-ink-primary"
                  style={{ fontFamily: "var(--font-cormorant-sc)" }}
                >
                  {article.title}
                </h3>
                <p className="mt-3 text-[15px] leading-relaxed text-ink-body">{article.body}</p>
                <span className="mt-6 inline-flex items-center text-[13px] font-medium text-gold">
                  Read article
                  <ArrowRight className="ml-1.5 h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-[#05080F] px-4 py-16 text-center text-[#D8E4F4] sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto max-w-[860px]">
          <h2
            className="text-[36px] font-bold leading-tight sm:text-[50px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            See how Operious eliminates the trust gap in enterprise AI operations.
          </h2>
          <Link
            href="/company/contact"
            className="mt-8 inline-flex h-12 items-center justify-center rounded-md bg-[#C9A84C] px-6 text-[14px] font-semibold text-[#05080F] transition-colors hover:bg-[#D4B85A]"
          >
            Request enterprise access
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </section>
    </main>
  );
}
