import Link from "next/link";
import {
  ArrowRight,
  Cpu,
  Landmark,
  RadioTower,
  ShieldCheck,
  Stethoscope,
  Truck,
} from "lucide-react";
import { AnimatedHeadline } from "@/components/animated-headline";
import { ContainmentLayer } from "@/components/containment-layer";
import { LiveEvidence } from "@/components/live-evidence";
import { ProofMarquee } from "@/components/proof-marquee";
import { Reveal, RevealGroup } from "@/components/reveal";
import { SplineHeroBg } from "@/components/spline-hero-bg";
import { Button } from "@/components/ui/button";
import { MagneticWrapper } from "@/components/magnetic-button";
import { TextRevealByWord } from "@/components/ui/text-reveal";
import { ContainerScroll } from "@/components/ui/container-scroll-animation";
import { CommandCenterPreview } from "@/components/command-center-preview";
import SkewCards from "@/components/ui/gradient-card-showcase";
import type { SkewCardProps } from "@/components/ui/gradient-card-showcase";
import { ZoomParallax } from "@/components/ui/zoom-parallax";
import FlowArt, { FlowSection } from "@/components/ui/story-scroll";

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

      {/* M7: ContainerScroll — Command Center reveal */}
      <section className="bg-[#F8F5EE] pt-20 pb-0">
        <ContainerScroll
          titleComponent={
            <div className="mb-8">
              <p
                className="text-[9px] uppercase tracking-[0.2em] text-gold-bright mb-3"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                Command Center
              </p>
              <h2
                className="text-[38px] font-extrabold leading-[1.05] tracking-[-0.02em] text-ink-primary sm:text-[54px]"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                The operational intelligence layer
                <br />
                your team actually uses.
              </h2>
              <p
                className="mt-4 text-[16px] text-ink-secondary max-w-[520px] mx-auto leading-[1.7]"
                style={{ fontFamily: "var(--font-inter, var(--type-geometric))" }}
              >
                A live view of every session, every governance decision, every approval — in one place.
              </p>
            </div>
          }
        >
          <CommandCenterPreview />
        </ContainerScroll>
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

      {/* M8: SkewCards — Capabilities */}
      <section className="bg-[#F8F5EE] px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
        <div className="mx-auto max-w-[1280px]">
          <RevealGroup>
            <Reveal>
              <SectionLabel>Capabilities</SectionLabel>
              <h2
                className="mt-5 max-w-[760px] text-[38px] font-extrabold leading-tight text-ink-primary sm:text-[54px]"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                The infrastructure enterprise AI actually requires.
              </h2>
            </Reveal>
          </RevealGroup>
          <SkewCards
            cards={[
              {
                title: "Constitutional Governance",
                desc: "Policy chains evaluate every proposed action. Fail-closed: no model output executes without passing governance. Empty chains return DENY.",
                gradientFrom: "#A8882C",
                gradientTo: "#C9A84C",
                ctaHref: "/platform/governance",
                ctaLabel: "Explore →",
              },
              {
                title: "Forensic Reconstructibility",
                desc: "Replay any decision at any point in time. UUID5 identity, HMAC signatures, and append-only timelines make every outcome defensible.",
                gradientFrom: "#1A4A9A",
                gradientTo: "#00C7FF",
                ctaHref: "/platform/replay",
                ctaLabel: "Explore →",
              },
              {
                title: "Multi-Agent Coordination",
                desc: "Deterministic orchestration across Diagnostic, Resolution, Supervisor, and Trainer agents — structural guarantees against deadlock.",
                gradientFrom: "#0D4A2A",
                gradientTo: "#30D158",
                ctaHref: "/platform/agents",
                ctaLabel: "Explore →",
              },
              {
                title: "Multilingual Operations",
                desc: "Arabic, English, and four further languages — language context preserved through triage, governance, and customer reply. Never silently dropped.",
                gradientFrom: "#4A1A7A",
                gradientTo: "#8B5CF6",
              },
              {
                title: "Crisis Override Control",
                desc: "Emergency rules activate in milliseconds. Block a SKU, halt a refund class, escalate a category — with automatic expiry and full audit evidence.",
                gradientFrom: "#7A1A1A",
                gradientTo: "#FF453A",
              },
              {
                title: "SOP Citation Intelligence",
                desc: "Every proposed resolution cited against your tenant SOP documents. No uncited claims. Every customer reply grounded in your own policies.",
                gradientFrom: "#3A4A1A",
                gradientTo: "#84CC16",
              },
            ] as SkewCardProps[]}
          />
        </div>
      </section>

      {/* M9: ZoomParallax — Platform showcase */}
      <section className="bg-[#050508] relative overflow-hidden">
        <div className="absolute top-16 left-16 z-10 pointer-events-none">
          <p
            className="text-[9px] uppercase tracking-[0.2em] text-[rgba(201,168,76,0.6)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            Platform
          </p>
        </div>
        <div className="absolute bottom-16 left-16 z-10 pointer-events-none">
          <h2
            className="text-[clamp(32px,5vw,64px)] font-extrabold leading-[1.05] tracking-[-0.02em] text-[#D8E4F4]"
            style={{ fontFamily: "var(--font-serif)" }}
          >
            Built for the<br />
            <em
              className="not-italic"
              style={{
                background: "linear-gradient(135deg,#A8882C,#C9A84C,#E8C76A)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
                fontStyle: "italic",
              }}
            >
              regulated
            </em>{" "}
            enterprise.
          </h2>
        </div>
        <ZoomParallax
          images={[
            { src: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1280&h=720&fit=crop&auto=format&q=80", alt: "Data analytics" },
            { src: "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=800&h=600&fit=crop&auto=format&q=80", alt: "Business operations" },
            { src: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=600&h=800&fit=crop&auto=format&q=80", alt: "Technology" },
            { src: "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=1280&h=720&fit=crop&auto=format&q=80", alt: "Security" },
            { src: "https://images.unsplash.com/photo-1498050108023-c5249f4df085?w=600&h=800&fit=crop&auto=format&q=80", alt: "Software" },
            { src: "https://images.unsplash.com/photo-1504868584819-f8e8b4b6d7e3?w=1280&h=720&fit=crop&auto=format&q=80", alt: "Data" },
            { src: "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop&auto=format&q=80", alt: "Network" },
          ]}
        />
      </section>

      {/* M10: FlowArt — Architecture narrative */}
      <FlowArt aria-label="Operious architecture narrative">
        <FlowSection
          aria-label="Boundary — governed admission"
          style={{ backgroundColor: "#050508", color: "#D8E4F4" }}
        >
          <p
            className="text-[9px] font-bold uppercase tracking-[0.2em] text-[rgba(201,168,76,0.5)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            01 — Boundary
          </p>
          <hr className="border-none border-t border-white/10 my-[2vw]" />
          <div>
            <h2
              className="text-[clamp(3.5rem,10vw,12rem)] font-extrabold leading-[0.88] uppercase tracking-tight"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              Admit<br />Only<br />The<br />Governed.
            </h2>
          </div>
          <hr className="border-none border-t border-white/10 my-[2vw]" />
          <p
            className="mt-auto max-w-[50ch] text-[clamp(1rem,2vw,1.5rem)] font-normal leading-relaxed text-[#7A90B4]"
            style={{ fontFamily: "var(--font-inter, var(--type-geometric))" }}
          >
            No request enters the system without passing the admission gate. Language detected, fingerprint computed, rate limits enforced — before any AI model sees the input.
          </p>
        </FlowSection>

        <FlowSection
          aria-label="Governance — policy executes"
          style={{ backgroundColor: "#0A0F1C", color: "#D8E4F4" }}
        >
          <p
            className="text-[9px] font-bold uppercase tracking-[0.2em] text-[rgba(0,199,255,0.5)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            02 — Governance
          </p>
          <hr className="border-none border-t border-white/[0.08] my-[2vw]" />
          <div>
            <h2
              className="text-[clamp(3.5rem,10vw,12rem)] font-extrabold leading-[0.88] uppercase tracking-tight"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              Policy<br />Executes.<br />Not<br />Suggests.
            </h2>
          </div>
          <hr className="border-none border-t border-white/[0.08] my-[2vw]" />
          <p
            className="mt-auto max-w-[50ch] text-[clamp(1rem,2vw,1.5rem)] font-normal leading-relaxed text-[#7A90B4]"
            style={{ fontFamily: "var(--font-inter, var(--type-geometric))" }}
          >
            Policy chains evaluate every proposed action. Empty chains return DENY. There is no path to ALLOW without a passing policy — regardless of what the model proposes.
          </p>
        </FlowSection>

        <FlowSection
          aria-label="Execution — governed actions"
          style={{ backgroundColor: "#F8F5EE", color: "#0A0F1C" }}
        >
          <p
            className="text-[9px] font-bold uppercase tracking-[0.2em] text-[rgba(168,136,44,0.7)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            03 — Execution
          </p>
          <hr className="border-none border-t border-black/15 my-[2vw]" />
          <div>
            <h2
              className="text-[clamp(3.5rem,10vw,12rem)] font-extrabold leading-[0.88] uppercase tracking-tight text-ink-primary"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              Every<br />Action.<br />Permitted<br />First.
            </h2>
          </div>
          <hr className="border-none border-t border-black/15 my-[2vw]" />
          <p
            className="mt-auto max-w-[50ch] text-[clamp(1rem,2vw,1.5rem)] font-normal leading-relaxed text-ink-body"
            style={{ fontFamily: "var(--font-inter, var(--type-geometric))" }}
          >
            Warranty claims, refund requests, replacements — each action is governed, SOP-cited, and optionally manager-approved before touching a customer.
          </p>
        </FlowSection>

        <FlowSection
          aria-label="Audit — permanent record"
          style={{ backgroundColor: "#050508", color: "#D8E4F4" }}
        >
          <p
            className="text-[9px] font-bold uppercase tracking-[0.2em] text-[rgba(201,168,76,0.5)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            04 — Audit
          </p>
          <hr className="border-none border-t border-white/10 my-[2vw]" />
          <div>
            <h2
              className="text-[clamp(3.5rem,10vw,12rem)] font-extrabold leading-[0.88] uppercase tracking-tight"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              Every<br />Decision.<br />Permanent<br />Record.
            </h2>
          </div>
          <hr className="border-none border-t border-white/10 my-[2vw]" />
          <p
            className="mt-auto max-w-[50ch] text-[clamp(1rem,2vw,1.5rem)] font-normal leading-relaxed text-[#7A90B4]"
            style={{ fontFamily: "var(--font-inter, var(--type-geometric))" }}
          >
            UUID5 identity. HMAC-SHA256 signatures. Append-only timelines. Replay any operational decision at any point in time with cryptographic certainty.
          </p>
        </FlowSection>
      </FlowArt>

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
