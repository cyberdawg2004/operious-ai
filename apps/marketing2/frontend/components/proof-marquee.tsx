"use client";

const proofPoints = [
  "Cryptographically Audited",
  "UUID5 Identity",
  "Force RLS on Every Table",
  "Append-Only Timelines",
  "Fail-Closed Governance",
  "ToolInvoker Enforcement",
  "Deterministic Replay",
  "Tenant-Isolated",
  "Multi-Agent Coordination",
  "Zero Silent Drops",
  "Six Languages Native",
];

export function ProofMarquee() {
  const doubled = [...proofPoints, ...proofPoints];
  return (
    <div className="w-full overflow-hidden border-y border-white/[0.04] bg-[#050508] py-5">
      <div className="flex animate-marquee gap-0 whitespace-nowrap">
        {doubled.map((item, i) => (
          <span key={i} className="flex shrink-0 items-center gap-3 px-7">
            <span className="w-[3px] h-[3px] rounded-full bg-[#30D158] shadow-[0_0_5px_rgba(48,209,88,0.7)]" />
            <span
              className="text-[9px] uppercase tracking-[0.12em] text-[#1A2E3E]"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {item}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
