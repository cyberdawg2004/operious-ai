"use client";

const proofPoints = [
  "Cryptographically Audited",
  "UUID5 Identity",
  "FORCE RLS",
  "Append-Only Timelines",
  "Fail-Closed Governance",
  "ToolInvoker Enforcement",
  "Deterministic Replay",
  "Tenant-Isolated",
  "Multi-Agent Coordination",
  "Zero Silent Drops",
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
