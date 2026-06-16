"use client";

import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { IntegrationMap } from "./operious-graphics";

const domains = [
  { name: "HARDWARE & CONSUMER ELECTRONICS", description: "RMA workflows, warranty triage, and refund authorization across multilingual customer touchpoints with cryptographic policy compliance." },
  { name: "FINANCIAL SERVICES & INSURANCE", description: "KYC exception handling, claims triage, dispute resolution, and underwriting workflow exceptions with full audit lineage." },
  { name: "HEALTHCARE OPERATIONS", description: "Prior authorization, claims appeals, eligibility verification, and patient intake exception handling within HIPAA-aligned tenant isolation." },
  { name: "LOGISTICS & SUPPLY CHAIN", description: "Exception-based routing decisions, carrier SLA enforcement, customs documentation validation, and delivery commitment management." },
  { name: "TELECOMMUNICATIONS", description: "Plan migration eligibility, contract exception handling, service restoration prioritization, and regulatory disclosure compliance." },
  { name: "PUBLIC SECTOR & UTILITIES", description: "Permit application triage, benefit eligibility determination, service restoration queuing, and compliance audit trail generation." },
];

export function DomainCards() {
  return (
    <section className="bg-[#f6efe5] px-4 py-20 sm:px-8 sm:py-28 lg:px-16 lg:py-40">
      <div className="mx-auto max-w-[1280px]">
        <div className="mb-12 sm:mb-16">
          <p className="mb-3 font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-gold sm:mb-4 sm:text-[11px]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>§03 · DOMAINS</p>
          <h2 className="mb-4 text-[36px] font-bold leading-[1.05] text-ink-primary sm:mb-6 sm:text-[48px] lg:text-[64px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>Built for operationally regulated environments.</h2>
          <p className="max-w-[760px] text-[15px] leading-relaxed text-ink-body sm:text-[16px] lg:text-[18px]">Operious deploys across industries where execution correctness, policy compliance, and forensic auditability are non-negotiable. Each deployment is tenant-isolated by default. Configuration, policies, and knowledge corpus are owned by the customer organization, not the platform.</p>
        </div>

        <div className="mb-10 grid grid-cols-1 gap-6 lg:grid-cols-[0.85fr_1.15fr] lg:gap-8">
          <div className="rounded-[32px] border border-[#e7dfcf] bg-[linear-gradient(135deg,rgba(255,255,255,0.94),rgba(248,242,232,0.96))] p-6 shadow-[0_24px_80px_rgba(5,8,15,0.08)] sm:p-8">
            <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-gold" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>integration layer</p>
            <h3 className="mt-4 text-[24px] font-semibold leading-[1.2] text-ink-primary sm:text-[28px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>Operious bridges channels and systems without weakening governance.</h3>
            <p className="mt-4 text-[14px] leading-[1.6] text-ink-body sm:text-[15px]">Every interaction arrives through a regulated boundary, is evaluated by policy, and is either executed or denied with evidence attached.</p>
          </div>
          <IntegrationMap />
        </div>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 lg:gap-8">
          {domains.map((domain, index) => (
            <motion.div key={index} className="group flex min-h-[220px] cursor-pointer flex-col gap-4 rounded-[24px] border border-[#e7dfcf] bg-[rgba(255,255,255,0.9)] p-6 shadow-[0_12px_40px_rgba(5,8,15,0.06)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_18px_60px_rgba(5,8,15,0.1)] sm:min-h-[260px] sm:p-8" initial={{ y: 0, boxShadow: "var(--shadow-card)" }} whileHover={{ y: -4, boxShadow: "var(--shadow-card-hover)" }} transition={{ duration: 0.24, ease: [0.4, 0, 0.2, 1] }}>
              <h3 className="text-[18px] font-semibold text-ink-primary sm:text-[20px] lg:text-[22px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>{domain.name}</h3>
              <p className="flex-grow text-[14px] leading-[1.6] text-ink-body sm:text-[15px]">{domain.description}</p>
              <motion.div className="flex items-center gap-1.5 text-gold" whileHover="hover">
                <span className="text-[13px] font-medium sm:text-[14px]">Learn more</span>
                <motion.span className="inline-block" variants={{ hover: { x: 4 } }} transition={{ duration: 0.24, ease: [0.4, 0, 0.2, 1] }}><ArrowRight className="h-[14px] w-[14px]" strokeWidth={1.5} /></motion.span>
              </motion.div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
