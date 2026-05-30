"use client";

const proofPoints = [
  "Policy decision audit in < 15ms",
  "100% of governed decisions produce permanent records",
  "HMAC-SHA256 signed — every trace",
  "Six languages — one governance standard",
  "Arabic gap closed for consumer electronics",
  "Warranty, refund, escalation — all governed",
  "Zero cross-tenant data access — by architecture",
  "Audit export available on demand",
  "Defect clusters detected automatically",
  "SOP knowledge updates on approval",
  "Crisis governance deployed in under one second",
  "Fraud quarantine before agent processing",
  "BAA available for healthcare",
  "Architecture review in 48 hours",
  "30-day deployment to production",
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
