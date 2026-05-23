"use client";

import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import Link from "next/link";

const domains = [
  {
    name: "HARDWARE & CONSUMER ELECTRONICS",
    href: "/industries/hardware",
    description:
      "RMA workflows, warranty triage, and refund authorization across multilingual customer touchpoints with cryptographic policy compliance.",
  },
  {
    name: "FINANCIAL SERVICES & INSURANCE",
    href: "/industries/financial-services",
    description:
      "KYC exception handling, claims triage, dispute resolution, and underwriting workflow exceptions with full audit lineage.",
  },
  {
    name: "HEALTHCARE OPERATIONS",
    href: "/industries/healthcare",
    description:
      "Prior authorization, claims appeals, eligibility verification, and patient intake exception handling within HIPAA-aligned tenant isolation.",
  },
  {
    name: "LOGISTICS & SUPPLY CHAIN",
    href: "/industries/logistics",
    description:
      "Exception-based routing decisions, carrier SLA enforcement, customs documentation validation, and delivery commitment management.",
  },
  {
    name: "TELECOMMUNICATIONS",
    href: "/industries/telecom",
    description:
      "Plan migration eligibility, contract exception handling, service restoration prioritization, and regulatory disclosure compliance.",
  },
  {
    name: "PUBLIC SECTOR & UTILITIES",
    href: "/industries/public-sector",
    description:
      "Permit application triage, benefit eligibility determination, service restoration queuing, and compliance audit trail generation.",
  },
];

export function DomainCards() {
  return (
    <section className="bg-canvas py-20 sm:py-28 lg:py-40 px-4 sm:px-8 lg:px-16">
      <div className="mx-auto max-w-[1280px]">
        {/* Section Header */}
        <div className="mb-12 sm:mb-16">
          <p
            className="font-mono text-[10px] sm:text-[11px] font-medium uppercase tracking-[0.18em] text-gold mb-3 sm:mb-4"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            §03 · DOMAINS
          </p>
          <h2
            className="text-[36px] sm:text-[48px] lg:text-[64px] font-bold text-ink-primary leading-[1.05] mb-4 sm:mb-6"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Built for operationally regulated environments.
          </h2>
          <p className="text-[15px] sm:text-[16px] lg:text-[18px] text-ink-body leading-relaxed max-w-[760px]">
            Operious deploys across industries where execution correctness,
            policy compliance, and forensic auditability are non-negotiable.
            Each deployment is tenant-isolated by default. Configuration,
            policies, and knowledge corpus are owned by the customer
            organization, not the platform.
          </p>
        </div>

        {/* 3x2 Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 lg:gap-8">
          {domains.map((domain) => (
            <Link key={domain.href} href={domain.href} className="block h-full">
              <motion.div
                className="group flex h-full flex-col gap-4 bg-white border border-border-subtle rounded-lg p-6 sm:p-8 min-h-[200px] sm:min-h-[240px] cursor-pointer"
                initial={{ y: 0, boxShadow: "var(--shadow-card)" }}
                whileHover={{
                  y: -4,
                  boxShadow: "var(--shadow-card-hover)",
                }}
                transition={{
                  duration: 0.24,
                  ease: "easeOut",
                }}
              >
                <h3
                  className="text-[18px] sm:text-[20px] lg:text-[22px] font-semibold text-ink-primary"
                  style={{ fontFamily: "var(--font-cormorant-sc)" }}
                >
                  {domain.name}
                </h3>
                <p className="text-[14px] sm:text-[15px] text-ink-body leading-[1.6] flex-grow">
                  {domain.description}
                </p>
                <motion.div 
                  className="flex items-center gap-1.5 text-gold"
                  whileHover="hover"
                >
                  <span className="text-[13px] sm:text-[14px] font-medium">Learn more</span>
                  <motion.span
                    className="inline-block"
                    variants={{
                      hover: { x: 4 }
                    }}
                    transition={{ duration: 0.24, ease: "easeOut" }}
                  >
                    <ArrowRight className="w-[14px] h-[14px]" strokeWidth={1.5} />
                  </motion.span>
                </motion.div>
              </motion.div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
