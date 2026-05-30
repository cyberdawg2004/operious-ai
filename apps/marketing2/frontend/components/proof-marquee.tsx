"use client";

const proofPoints = [
  "Policy enforced before execution",
  "100% of decisions auditable",
  "Full forensic replay from any checkpoint",
  "Six languages. One governance layer.",
  "FORCE RLS on every tenant table",
  "Zero silent drops",
  "Approval workflows with full evidence",
  "Warranty, refund, escalation - governed",
  "Defect clusters detected automatically",
  "SOP knowledge updates on approval",
  "Crisis deployment in under one second",
  "Fraud quarantine before agent processing",
  "Architecture review in 48 hours",
  "BAA available for healthcare",
];

export function ProofMarquee() {
  const doubled = [...proofPoints, ...proofPoints];

  return (
    <div className="w-full overflow-hidden border-y border-[#1A2744] bg-[#05080F] py-5">
      <div className="flex animate-marquee gap-16 whitespace-nowrap">
        {doubled.map((item, i) => (
          <span
            key={i}
            className="flex shrink-0 items-center gap-16 text-xs font-mono uppercase tracking-[0.2em] text-[#2A5CAA]/50"
          >
            {item}
            <span className="text-[#1A2744]">·</span>
          </span>
        ))}
      </div>
    </div>
  );
}
