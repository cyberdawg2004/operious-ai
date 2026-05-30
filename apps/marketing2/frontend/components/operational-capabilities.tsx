"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";

import { BorderBeam } from "@/components/ui/border-beam";

const capabilityGroups = [
  {
    label: "Omnichannel Operations",
    title: "Every channel. One governance layer.",
    items: [
      {
        title: "Voice",
        body: "Inbound calls answered by AI agents with turn-taking and barge-in detection. No customer-facing queue. If capacity is reached, calls are declined immediately - not held. 100 concurrent calls per deployment node, horizontally scalable.",
      },
      {
        title: "Real-time chat",
        body: "Progressive responses delivered under 500ms. The system acknowledges immediately and produces the governed response as context is processed. Customers never wait for a loading state.",
      },
      {
        title: "Email and messaging",
        body: "Email, WhatsApp Business, and web chat processed through the same governance chain. Case continuity maintained across channels. A follow-up on WhatsApp continues the same governed session as the original email.",
      },
    ],
  },
  {
    label: "Language Operations",
    title: "Six languages. One operational standard.",
    intro:
      "Language detection fires at ingress - 97% accuracy on first contact. The ticket is translated to canonical English for processing, classified by the AI, responded to in English, and translated back to the customer language before delivery.",
    items: ["Arabic", "English", "Indonesian", "Spanish", "French", "Chinese (Simplified)"].map(
      (language) => ({
        title: language,
        body: "Detected. Classified. Responded. Audited.",
      })
    ),
    note:
      "Arabic language operations close a documented gap in most enterprise BPO deployments. Native right-to-left processing. Governance-consistent response quality.",
  },
  {
    label: "Autonomous Actions",
    title: "AI proposes. Policy decides. Records prove.",
    items: [
      {
        title: "Warranty operations",
        body: "Warranty claims evaluated against policy thresholds. Claims within policy execute automatically. Claims above threshold route to manager approval with full evidence context. Every outcome produces a permanent governance record.",
      },
      {
        title: "Refund authorization",
        body: "Refund requests evaluated against configured limits. Low-risk refunds authorized and executed automatically. High-value or out-of-policy refunds suspend for human review. No refund executes without a persisted authorization decision.",
      },
      {
        title: "Replacement and repair",
        body: "Replacement orders trigger for qualifying defects. Warehouse repair reports dispatch to engineering teams via Jira or Linear. Every replacement and repair action is auditable from first customer contact to fulfillment.",
      },
      {
        title: "Escalation routing",
        body: "Escalations route by policy-defined criteria. The human reviewer receives full session context, classification evidence, governance history, and the specific reason for escalation before reading the first message.",
      },
    ],
  },
  {
    label: "Fraud and Security",
    title: "Coordinated fraud identified before it reaches agents.",
    flow: true,
    items: [
      {
        title: "Fingerprint",
        metric: "0.25ms",
        body: "Every incoming ticket receives a MinHash fingerprint - 128 hash functions applied to 3-gram tokenization on the ingress hot path.",
      },
      {
        title: "Cluster detection",
        metric: "5-minute window",
        body: "A sliding window monitors tenant-level fingerprint similarity. Five or more contacts above 70% similarity trips the semantic circuit automatically.",
      },
      {
        title: "Quarantine and review",
        metric: "No agent exposure",
        body: "Matching contacts route to isolated quarantine. Operators confirm fraud or false positive before standard processing resumes.",
      },
    ],
  },
  {
    label: "Operational Intelligence",
    title: "The platform learns from operations. Continuously.",
    items: [
      {
        title: "Defect cluster detection",
        body: "When the same product failure appears across multiple support contacts within a configurable window, Operious detects the pattern automatically. No analyst required.",
      },
      {
        title: "Engineering report synthesis",
        body: "When a cluster is detected, an LLM synthesizes a technical engineering defect report from accumulated evidence. Governance evaluates the report before dispatch.",
      },
      {
        title: "Automated dispatch",
        body: "Approved reports dispatch to Jira or Linear through a governed outbound channel with retry discipline and delivery tracking.",
      },
      {
        title: "SOP failure detection",
        body: "When operational quality drops below threshold across a category, Operious detects the failure pattern from QA scoring and escalated contact signals.",
      },
      {
        title: "SOP improvement synthesis",
        body: "The platform synthesizes a proposed SOP improvement using the existing knowledge base as context and routes it to a manager with full evidence.",
      },
      {
        title: "Knowledge base update",
        body: "On manager approval, the SOP document updates immediately, the knowledge base re-indexes automatically, and the improvement is active on the next contact.",
      },
    ],
  },
  {
    label: "Governance and Crisis",
    title: "Emergency governance deployed in under one second.",
    items: [
      {
        title: "Crisis deployment",
        body: "Four pre-built crisis templates deploy in milliseconds via the Command Center: block a SKU, halt refunds, escalate every contact, or freeze a workflow category. Redis activation enforces the rule on the next contact.",
      },
      {
        title: "Crisis audit trail",
        body: "Every crisis deployment creates immutable audit events for actor, template, scope, time, TTL expiry, and manual deactivation. The crisis history is permanent and non-modifiable.",
      },
      {
        title: "Governance policy invalidation",
        body: "When policy changes, the singleton governance runtime reloads on invalidation signals so updates take effect on the next incoming contact, not the next deployment.",
      },
    ],
  },
];

export function OperationalCapabilities() {
  const [activeIndex, setActiveIndex] = useState(0);
  const active = capabilityGroups[activeIndex];

  return (
    <section className="bg-canvas px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
      <div className="mx-auto max-w-[1280px]">
        <p
          className="text-[10px] uppercase tracking-[0.18em] text-gold"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          Operational capabilities
        </p>
        <div className="mt-5 grid gap-5 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
          <h2
            className="max-w-[720px] text-[38px] font-bold leading-tight text-ink-primary sm:text-[54px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Complete operational workflow coverage. Governed end-to-end.
          </h2>
          <p className="text-[16px] leading-relaxed text-ink-body">
            Every capability below executes under a governance chain. Every action
            produces an immutable audit record. Every outcome is reconstructible at
            any future point in time.
          </p>
        </div>

        <div className="mt-10 flex flex-wrap gap-2">
          {capabilityGroups.map((group, index) => (
            <button
              key={group.label}
              type="button"
              aria-pressed={activeIndex === index}
              onClick={() => setActiveIndex(index)}
              className={`rounded-md border px-3 py-2 text-[12px] font-semibold transition-all duration-200 ${
                activeIndex === index
                  ? "border-[#C9A84C] bg-[#05080F] text-[#D8E4F4]"
                  : "border-border-subtle bg-white text-ink-secondary hover:border-gold hover:text-ink-primary"
              }`}
            >
              {group.label}
            </button>
          ))}
        </div>

        <div className="relative mt-6 overflow-hidden rounded-md border border-[#1A2744] bg-[#05080F] p-6 text-[#D8E4F4] shadow-[0_28px_80px_rgba(0,0,0,0.18)] sm:p-8">
          <BorderBeam duration={18} />
          <h3
            className="text-[30px] font-bold leading-tight sm:text-[42px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            {active.title}
          </h3>
          {active.intro && (
            <p className="mt-4 max-w-4xl text-[15px] leading-relaxed text-[#A9B8CE]">
              {active.intro}
            </p>
          )}

          <div
            className={`mt-8 grid gap-4 ${
              active.items.length > 4
                ? "md:grid-cols-2 xl:grid-cols-3"
                : "md:grid-cols-3"
            }`}
          >
            {active.items.map((item, index) => (
              <article
                key={item.title}
                className="relative rounded-md border border-[#1A2744] bg-[#0B1120] p-5 transition-all duration-300 hover:-translate-y-1 hover:border-[#C9A84C]"
              >
                <div className="flex items-start justify-between gap-4">
                  <h4 className="text-[15px] font-semibold uppercase tracking-[0.12em]">
                    {item.title}
                  </h4>
                  {"metric" in item && item.metric && (
                    <span className="rounded border border-[#2A5CAA]/40 px-2 py-1 font-mono text-[10px] text-[#C9A84C]">
                      {item.metric}
                    </span>
                  )}
                </div>
                <p className="mt-4 text-[14px] leading-relaxed text-[#7A90B4]">
                  {item.body}
                </p>
                {active.flow && index < active.items.length - 1 && (
                  <ArrowRight className="absolute -right-3 top-1/2 hidden h-5 w-5 -translate-y-1/2 text-[#C9A84C] md:block" />
                )}
              </article>
            ))}
          </div>
          {active.note && (
            <p className="mt-6 rounded-md border border-[#C9A84C]/25 bg-[#C9A84C]/10 p-4 text-[14px] leading-relaxed text-[#D8E4F4]">
              {active.note}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
