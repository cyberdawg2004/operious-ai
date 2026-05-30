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
import { AnimatedHeadline } from "@/components/animated-headline";
import { ContainmentLayer } from "@/components/containment-layer";
import { FeatureCard } from "@/components/feature-card";
import { LiveEvidence } from "@/components/live-evidence";
import { ProofMarquee } from "@/components/proof-marquee";
import { Reveal, RevealGroup } from "@/components/reveal";
import { ParallaxBlock, ScrollHighlight } from "@/components/scroll-fx";
import { SplineHeroBg } from "@/components/spline-hero-bg";
import { Button } from "@/components/ui/button";
import { MagneticWrapper } from "@/components/magnetic-button";
import { TextRevealByWord } from "@/components/ui/text-reveal";

const pillars = [
  {
    title: "Constitutional Governance",
    body: "Policies execute, not suggest. Decisions cannot bypass the governance layer.",
    href: "/platform/governance",
    icon: Scale,
    iconName: "governance" as const,
  },
  {
    title: "Reconstructible Truth",
    body: "Replay any operational decision at any point in time with cryptographic certainty.",
    href: "/platform/replay",
    icon: FileSearch,
    iconName: "replay" as const,
  },
  {
    title: "Multi-Agent Coordination",
    body: "Deterministic agent orchestration with structural guarantees against deadlock and conflict.",
    href: "/platform/agents",
    icon: Network,
    iconName: "agents" as const,
  },
  {
    title: "AGI-Ready Governance",
    body:
      "Enterprise AI models are becoming more powerful every month. " +
      "Most companies are afraid to deploy them — there is no safety " +
      "layer between what the model decides and what it executes. " +
      "Operious is that layer. Any autonomous AI model. Any action. " +
      "Governed. Audited. Replayable.",
    href: "/platform/governance",
    icon: ShieldCheck,
    iconName: "agi" as const,
  },
];

const containmentLayers = [
  {
    number: "01",
    title: "ToolInvoker Enforcement",
    description:
      "LLM output is a proposal, not a command. Every action " +
      "passes through ToolInvoker before execution. The model " +
      "cannot bypass it.",
  },
  {
    number: "02",
    title: "Governance Substrate",
    description:
      "Policy chains evaluate every proposed action. Empty chains " +
      "return DENY. There is no path to ALLOW without a passing policy.",
  },
  {
    number: "03",
    title: "Row-Level Security",
    description:
      "FORCE RLS on every tenant-scoped table. No query reaches " +
      "data it is not authorized to see, regardless of what the " +
      "AI model instructs.",
  },
  {
    number: "04",
    title: "UUID5 Identity",
    description:
      "Every decision, every agent, every execution is " +
      "cryptographically fingerprinted. Deterministic. " +
      "Replayable. Forensically reconstructible.",
  },
  {
    number: "05",
    title: "Append-Only Timelines",
    description:
      "No event can be modified after creation. The audit trail " +
      "is immutable by architecture, not by policy.",
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
    <main className="flex-1 overflow-x-hidden">
      <section className="relative overflow-hidden bg-[#05080F] px-4 pb-16 pt-32 text-[#D8E4F4] sm:px-8 sm:pb-20 sm:pt-40 lg:px-16 lg:pb-24">
        <SplineHeroBg />
        {/* Background radial gradient */}
        <div className="pointer-events-none absolute inset-0 z-[1] bg-[radial-gradient(ellipse_100%_60%_at_50%_0%,rgba(42,92,170,0.10)_0%,transparent_70%)]" />
        <div
          className="pointer-events-none absolute inset-0 z-[1] opacity-[0.07]"
          style={{
            backgroundImage:
              "linear-gradient(#D8E4F4 1px, transparent 1px), linear-gradient(90deg, #D8E4F4 1px, transparent 1px)",
            backgroundSize: "64px 64px",
          }}
        />
        <RevealGroup
          className="relative z-10 mx-auto flex max-w-[1320px] flex-col items-center gap-10 lg:min-h-[calc(100vh-160px)] lg:justify-center text-center"
          mode="load"
        >
          {/* Eyebrow */}
          <Reveal>
            <div className="inline-flex items-center gap-3">
              <span className="w-7 h-px bg-gold-bright" />
              <span
                className="text-[9px] uppercase tracking-[0.22em] text-gold-bright"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                Governed Execution Infrastructure
              </span>
              <span className="w-7 h-px bg-gold-bright" />
            </div>
          </Reveal>

          {/* Headline */}
          <div className="w-full max-w-[960px]">
            <Reveal>
              <AnimatedHeadline
                className="text-[52px] font-extrabold leading-[0.93] tracking-[-0.02em] sm:text-[72px] lg:text-[108px] text-[#D8E4F4]"
                accentWords={["governs", "AI"]}
              >
                The runtime that governs AI at scale.
              </AnimatedHeadline>
            </Reveal>
          </div>

          {/* Subheadline */}
          <Reveal>
            <p
              className="max-w-[640px] text-[18px] leading-[1.75] text-[#7A90B4] font-normal"
              style={{ fontFamily: "var(--font-inter, var(--type-geometric))" }}
            >
              The runtime between AI decisions and enterprise actions — governed
              by policy, permanently reconstructible, and auditable to the byte.
            </p>
          </Reveal>

          {/* CTAs */}
          <Reveal>
            <div className="flex flex-col gap-3 sm:flex-row justify-center">
              <MagneticWrapper>
                <Button
                  href="/company/contact"
                  variant="primary"
                  className="shadow-[0_12px_34px_rgba(201,168,76,0.22)] hover:shadow-[0_18px_44px_rgba(201,168,76,0.34)]"
                >
                  Request enterprise access
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </MagneticWrapper>
              <Button
                href="/platform"
                variant="ghost"
                className="bg-[#0B1120]/60 hover:shadow-[0_16px_36px_rgba(42,107,204,0.22)]"
              >
                Explore the architecture
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </Reveal>

          {/* 7-substrate strip */}
          <Reveal>
            <div className="flex border border-white/[0.05] rounded-xl overflow-hidden bg-white/[0.014] backdrop-blur-md max-w-[700px] w-full">
              {["Boundary","Coordination","Governance","Session","Execution","Supervisor","Arbitration"].map((name, i) => (
                <div
                  key={name}
                  className="flex-1 py-[14px] px-2 text-center border-r border-white/[0.04] last:border-r-0 hover:bg-[rgba(201,168,76,0.05)] transition-colors group cursor-default"
                >
                  <div
                    className="text-[8px] text-[rgba(201,168,76,0.45)] font-mono tracking-[0.12em] mb-1 group-hover:text-[var(--gold)] transition-colors"
                  >
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div className="text-[10px] text-[#2E3E50] font-medium tracking-[0.03em] group-hover:text-[#7A90B4] transition-colors">
                    {name}
                  </div>
                </div>
              ))}
            </div>
          </Reveal>
        </RevealGroup>
      </section>

      <ProofMarquee />

      {/* TextRevealByWord bridge */}
      <section className="bg-[#050508] py-0">
        <TextRevealByWord
          text="Every enterprise AI deployment needs a governance layer between what the model proposes and what the system executes. Operious is that layer."
          className="text-[#D8E4F4]/20"
        />
      </section>

      <section className="border-y border-border-subtle bg-canvas px-4 py-8 sm:px-8 lg:px-16">
        <RevealGroup className="mx-auto max-w-[1320px]">
          <Reveal>
            <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <SectionLabel>Enterprise operating domains</SectionLabel>
                <p className="mt-2 max-w-[640px] text-[15px] leading-relaxed text-ink-body">
                  Designed for regulated teams where operational decisions must remain governed,
                  replayable, and tenant-contained.
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
                {industries.map((industry) => {
                  const Icon = industry.icon;
                  return (
                    <Link
                      key={industry.href}
                      href={industry.href}
                      className="group flex h-16 items-center gap-3 rounded border border-border-subtle bg-white px-3 transition-all duration-300 hover:-translate-y-0.5 hover:border-gold hover:shadow-[var(--shadow-card-hover)]"
                    >
                      <Icon className="h-4 w-4 shrink-0 text-gold" />
                      <span className="text-[12px] font-semibold text-ink-primary">
                        {industry.title}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          </Reveal>
        </RevealGroup>
      </section>

      <section className="bg-canvas px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
        <div className="mx-auto max-w-[1280px]">
          <RevealGroup>
            <Reveal>
              <SectionLabel>Core features</SectionLabel>
              <h2
                className="mt-5 max-w-[760px] text-[38px] font-bold leading-tight text-ink-primary sm:text-[54px]"
                style={{ fontFamily: "var(--font-cormorant-sc)" }}
              >
                The control plane enterprise AI operations usually lacks.
              </h2>
            </Reveal>
            <div className="mt-10 grid gap-5 lg:grid-cols-2 xl:grid-cols-4">
              {pillars.map((pillar, index) => (
                <FeatureCard
                  key={pillar.title}
                  title={pillar.title}
                  body={pillar.body}
                  href={pillar.href}
                  iconName={pillar.iconName}
                  index={index}
                />
              ))}
            </div>
          </RevealGroup>
        </div>
      </section>

      <section className="bg-[#05080F] px-4 py-20 text-[#D8E4F4] sm:px-8 sm:py-24 lg:px-16">
        <RevealGroup className="mx-auto grid max-w-[1280px] gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
          <Reveal>
          <div>
            <SectionLabel>Value proposition</SectionLabel>
            <h2
              className="mt-5 text-[38px] font-bold leading-tight sm:text-[54px]"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              A substrate diagram for governed execution.
            </h2>
            <ScrollHighlight
              className="mt-6 text-[16px] leading-relaxed"
              text="Operious does not place a chatbot over an enterprise queue. The runtime separates authority into seven substrates so tenant boundaries, agent coordination, policy admission, execution, supervision, and conflict handling can be inspected independently."
              baseColor="#5C6B85"
              litColor="#D8E4F4"
              accentColor="#C9A84C"
            />
            <Link
              href="/platform"
              className="mt-8 inline-flex h-12 items-center justify-center rounded-md bg-[#C9A84C] px-5 text-[14px] font-semibold text-[#05080F] shadow-[0_12px_34px_rgba(201,168,76,0.18)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-[#D4B85A] hover:shadow-[0_18px_44px_rgba(201,168,76,0.26)]"
            >
              Explore platform architecture
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </div>
          </Reveal>
          <Reveal>
          <ParallaxBlock intensity={0.22}>
          <div className="rounded-md border border-[#1A2744] bg-[#0B1120] p-5 shadow-[0_28px_80px_rgba(0,0,0,0.24)]">
            <div className="grid gap-3">
              {architectureLayers.map((layer, index) => (
                <div
                  key={layer}
                  className="flex items-center justify-between rounded-md border border-[#1A2744] bg-[#05080F] px-5 py-4 transition-all duration-300 hover:-translate-y-0.5 hover:border-[#C9A84C]"
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
          </ParallaxBlock>
          </Reveal>
        </RevealGroup>
      </section>

      {/* Containment Vessel */}
      <section className="border-t border-[#1A2744] bg-[#05080F] px-6 py-24">
        <div className="mx-auto max-w-5xl">
          <div className="mb-16">
            <p className="mb-4 font-mono text-xs uppercase tracking-[0.25em] text-[#7A90B4]">
              Architecture
            </p>
            <h2 className="text-3xl font-light tracking-tight text-[#D8E4F4]">
              The Containment Vessel
            </h2>
            <p className="mt-4 max-w-2xl leading-relaxed text-[#7A90B4]">
              Five layers that no AI model can bypass. The separation between what the
              model proposes and what it is permitted to execute is not policy — it is
              architecture.
            </p>
          </div>

          <div className="space-y-0">
            {containmentLayers.map((layer, i) => (
              <ContainmentLayer key={i} index={i} {...layer} />
            ))}
          </div>
        </div>
      </section>

      <LiveEvidence />

      <section className="bg-canvas px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
        <RevealGroup className="mx-auto max-w-[1280px]">
          <Reveal>
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
          </Reveal>
          <div className="mt-10 grid gap-5 lg:grid-cols-3">
            {trustCards.map((card) => (
              <Reveal key={card.title}>
              <article className="h-full rounded-md border border-border-subtle bg-white p-6 transition-all duration-300 hover:-translate-y-1 hover:border-gold hover:shadow-[var(--shadow-card-hover)]">
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
              </Reveal>
            ))}
          </div>
        </RevealGroup>
      </section>

      <section className="bg-surface-raised px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
        <RevealGroup className="mx-auto max-w-[1280px]">
          <Reveal>
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
          </Reveal>
          <div className="mt-10 grid gap-5 lg:grid-cols-3">
            {featuredArticles.map((article) => (
              <Reveal key={article.href}>
              <Link
                href={article.href}
                className="group block h-full rounded-md border border-border-subtle bg-white p-6 transition-all duration-300 hover:-translate-y-1 hover:border-gold hover:shadow-[var(--shadow-card-hover)]"
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
              </Reveal>
            ))}
          </div>
        </RevealGroup>
      </section>

      <section className="bg-[#05080F] px-4 py-16 text-center text-[#D8E4F4] sm:px-8 sm:py-20 lg:px-16">
        <RevealGroup className="mx-auto max-w-[860px]">
          <Reveal>
          <h2
            className="text-[36px] font-bold leading-tight sm:text-[50px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            See how Operious eliminates the trust gap in enterprise AI operations.
          </h2>
          <Link
            href="/company/contact"
            className="mt-8 inline-flex h-12 items-center justify-center rounded-md bg-[#C9A84C] px-6 text-[14px] font-semibold text-[#05080F] shadow-[0_12px_34px_rgba(201,168,76,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-[#D4B85A] hover:shadow-[0_18px_44px_rgba(201,168,76,0.28)]"
          >
            Request enterprise access
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
          </Reveal>
        </RevealGroup>
      </section>
    </main>
  );
}
