"use client";

import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";

const domains = [
  {
    name: "HARDWARE & CONSUMER ELECTRONICS",
    description:
      "RMA workflows, warranty triage, and refund authorization across multilingual customer touchpoints with cryptographic policy compliance.",
  },
  {
    name: "FINANCIAL SERVICES & INSURANCE",
    description:
      "KYC exception handling, claims triage, dispute resolution, and underwriting workflow exceptions with full audit lineage.",
  },
  {
    name: "HEALTHCARE OPERATIONS",
    description:
      "Prior authorization, claims appeals, eligibility verification, and patient intake exception handling within HIPAA-aligned tenant isolation.",
  },
  {
    name: "LOGISTICS & SUPPLY CHAIN",
    description:
      "Exception-based routing decisions, carrier SLA enforcement, customs documentation validation, and delivery commitment management.",
  },
  {
    name: "TELECOMMUNICATIONS",
    description:
      "Plan migration eligibility, contract exception handling, service restoration prioritization, and regulatory disclosure compliance.",
  },
  {
    name: "PUBLIC SECTOR & UTILITIES",
    description:
      "Permit application triage, benefit eligibility determination, service restoration queuing, and compliance audit trail generation.",
  },
];

export function DomainCards() {
  return (
    <section className="bg-canvas py-[160px] px-16">
      <div className="mx-auto max-w-[1280px]">
        {/* Section Header */}
        <div className="mb-16">
          <p
            className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-gold mb-4"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            §03 · DOMAINS
          </p>
          <h2
            className="text-[64px] font-bold text-ink-primary leading-[1.05] mb-6"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Built for operationally regulated environments.
          </h2>
          <p className="text-[18px] text-ink-body leading-relaxed max-w-[760px]">
            Operious deploys across industries where execution correctness,
            policy compliance, and forensic auditability are non-negotiable.
            Each deployment is tenant-isolated by default. Configuration,
            policies, and knowledge corpus are owned by the customer
            organization, not the platform.
          </p>
        </div>

        {/* 3x2 Grid */}
        <div className="grid grid-cols-3 gap-8">
          {domains.map((domain, index) => (
            <motion.div
              key={index}
              className="group flex flex-col gap-4 bg-white border border-border-subtle rounded-lg p-8 min-h-[240px] cursor-pointer"
              initial={{ y: 0, boxShadow: "0 1px 0 var(--border-subtle)" }}
              whileHover={{
                y: -4,
                boxShadow: "0 8px 24px rgba(10,15,28,0.08)",
              }}
              transition={{
                duration: 0.24,
                ease: [0.4, 0, 0.2, 1],
              }}
            >
              <h3
                className="text-[22px] font-semibold text-ink-primary"
                style={{ fontFamily: "var(--font-cormorant-sc)" }}
              >
                {domain.name}
              </h3>
              <p className="text-[15px] text-ink-body leading-[1.6] flex-grow">
                {domain.description}
              </p>
              <div className="flex items-center gap-1.5 text-gold">
                <span className="text-[14px] font-medium">Learn more</span>
                <motion.span
                  className="inline-block"
                  initial={{ x: 0 }}
                  whileHover={{ x: 4 }}
                  transition={{ duration: 0.24, ease: [0.4, 0, 0.2, 1] }}
                >
                  <ArrowRight className="w-[14px] h-[14px]" strokeWidth={1.5} />
                </motion.span>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
