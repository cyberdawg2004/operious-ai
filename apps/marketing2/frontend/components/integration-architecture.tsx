"use client";

import { useRef, type RefObject } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { AnimatedBeam } from "@/components/ui/animated-beam";
import { OperioussLogo } from "@/components/logo";

const inboundChannels = [
  "Email",
  "WhatsApp Business",
  "Voice (Twilio)",
  "Web Chat",
  "Zendesk",
  "Shulex",
  "Lark",
];

const connectedSystems = [
  "Jira",
  "Linear",
  "Your CRM",
  "Salesforce",
  "ServiceNow",
  "Warehouse System",
  "Compliance Export",
  "Audit Record",
];

function Zone({
  title,
  items,
  refProp,
}: {
  title: string;
  items: string[];
  refProp: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div
      ref={refProp}
      className="rounded-md border border-[#1A2744] bg-[#0B1120] p-5"
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-[#C9A84C]">
        {title}
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {items.map((item) => (
          <span
            key={item}
            className="rounded border border-[#1A2744] bg-[#05080F] px-2.5 py-1.5 text-[12px] text-[#D8E4F4]"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

export function IntegrationArchitecture() {
  const containerRef = useRef<HTMLDivElement>(null);
  const leftRef = useRef<HTMLDivElement>(null);
  const centerRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);

  return (
    <section className="bg-[#05080F] px-4 py-20 text-[#D8E4F4] sm:px-8 sm:py-24 lg:px-16">
      <div className="mx-auto max-w-[1280px]">
        <p
          className="text-[10px] uppercase tracking-[0.18em] text-[#C9A84C]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          Integration architecture
        </p>
        <div className="mt-5 grid gap-5 lg:grid-cols-[0.9fr_1.1fr] lg:items-end">
          <h2
            className="max-w-[760px] text-[38px] font-bold leading-tight sm:text-[54px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Operious operates within your existing stack. Not instead of it.
          </h2>
          <p className="text-[15px] leading-relaxed text-[#7A90B4]">
            The governance layer sits between your AI models and your customers,
            your systems of record, and your operations team - without displacing
            your CRM, ticketing platform, telephony, or helpdesk infrastructure.
          </p>
        </div>

        <div
          ref={containerRef}
          className="relative mt-10 grid gap-5 overflow-hidden rounded-md border border-[#1A2744] bg-[#05080F] p-5 sm:p-6 lg:grid-cols-[1fr_0.72fr_1fr] lg:items-center"
        >
          <AnimatedBeam
            containerRef={containerRef}
            fromRef={leftRef}
            toRef={centerRef}
            curvature={40}
            duration={5}
          />
          <AnimatedBeam
            containerRef={containerRef}
            fromRef={centerRef}
            toRef={rightRef}
            curvature={-40}
            duration={5}
            delay={1.2}
          />

          <Zone title="Inbound channels" items={inboundChannels} refProp={leftRef} />

          <div
            ref={centerRef}
            className="relative rounded-md border border-[#C9A84C]/30 bg-[#0B1120] p-6 text-center shadow-[0_0_60px_rgba(201,168,76,0.16)]"
          >
            <div className="mx-auto flex justify-center">
              <OperioussLogo size={32} showWordmark tone="dark" />
            </div>
            <p className="mt-5 text-[20px] font-semibold">
              Governance. Execution. Audit.
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-[#7A90B4]">
              Policy admission between proposed action and operational execution.
            </p>
          </div>

          <Zone title="Connected systems" items={connectedSystems} refProp={rightRef} />
        </div>

        <p className="mx-auto mt-6 max-w-[880px] text-center text-[15px] leading-relaxed text-[#7A90B4]">
          Operious does not require replacing your helpdesk, CRM, or telephony
          system. It adds a governance and audit layer to the operational actions
          your existing systems initiate.
        </p>
        <div className="mt-6 flex justify-center">
          <Link
            href="/platform/integrations"
            className="inline-flex h-12 items-center justify-center rounded-md border border-[#1A2744] px-5 text-[14px] font-semibold text-[#D8E4F4] transition-all duration-300 hover:-translate-y-0.5 hover:border-[#C9A84C]/40 hover:text-[#C9A84C]"
          >
            View integration matrix
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}
