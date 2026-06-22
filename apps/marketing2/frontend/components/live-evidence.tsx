"use client";

import { useState } from "react";
import { motion } from "framer-motion";

const evidenceTraces = {
  allow: {
    label: "ALLOW",
    header: "pilot-account · consumer-electronics · Session df6139ba · 2026-05-24T03:10:28Z · LIVE",
    statusColor: "text-green-400/80",
    rows: [
      {
        label: "CLASSIFICATION",
        value: "charging_issue",
        accent: "0.93 confidence",
        color: "text-[#D8E4F4]",
      },
      {
        label: "GOVERNANCE",
        value: "ALLOW",
        accent: "confidence_thresholds v1",
        color: "text-green-400/80",
      },
      {
        label: "SOP CITATIONS",
        value: "Charging Policy v3",
        accent: "score 0.8921",
        color: "text-[#D8E4F4]",
      },
      {
        label: "AUDIT SIGNATURE",
        value: "HMAC-SHA256",
        accent: "e5de882a...9aac",
        color: "text-[#A8882C]/80",
      },
      {
        label: "REPLAY",
        value: "Forensically reconstructible",
        accent: "from any checkpoint",
        color: "text-[#7A90B4]",
      },
    ],
  },
  deny: {
    label: "DENY",
    header: "consumer-electronics · Session 8b7a2c1f · LIVE",
    statusColor: "text-[#C9A84C]",
    rows: [
      {
        label: "CLASSIFICATION",
        value: "refund_request",
        accent: "0.91 confidence",
        color: "text-[#D8E4F4]",
      },
      {
        label: "GOVERNANCE",
        value: "DENY",
        accent: "refund_policy_v2",
        color: "text-[#C9A84C]",
      },
      {
        label: "REASON",
        value: "Request exceeds policy threshold",
        accent: "$247 > $50 limit",
        color: "text-[#D8E4F4]",
      },
      {
        label: "ACTION",
        value: "Manager approval required",
        accent: "execution blocked",
        color: "text-[#7A90B4]",
      },
      {
        label: "AUDIT SIGNATURE",
        value: "HMAC-SHA256",
        accent: "f3a219c4...7bde",
        color: "text-[#A8882C]/80",
      },
      {
        label: "REPLAY",
        value: "Reconstructible",
        accent: "from any checkpoint",
        color: "text-[#7A90B4]",
      },
    ],
  },
  escalate: {
    label: "ESCALATE",
    header: "consumer-electronics · Session 4d9f1a83 · LIVE",
    statusColor: "text-[#7A90B4]",
    rows: [
      {
        label: "CLASSIFICATION",
        value: "technical_issue",
        accent: "0.78 confidence",
        color: "text-[#D8E4F4]",
      },
      {
        label: "GOVERNANCE",
        value: "ESCALATE",
        accent: "confidence_threshold_gate_v1",
        color: "text-[#7A90B4]",
      },
      {
        label: "REASON",
        value: "Confidence below escalation threshold",
        accent: "0.78 < 0.85",
        color: "text-[#D8E4F4]",
      },
      {
        label: "ROUTED",
        value: "Human review queue",
        accent: "full session context attached",
        color: "text-[#7A90B4]",
      },
      {
        label: "AUDIT SIGNATURE",
        value: "HMAC-SHA256",
        accent: "9c3e45b1...2d7f",
        color: "text-[#A8882C]/80",
      },
      {
        label: "REPLAY",
        value: "Reconstructible",
        accent: "from any checkpoint",
        color: "text-[#7A90B4]",
      },
    ],
  },
};

type EvidenceTraceKey = keyof typeof evidenceTraces;

export function LiveEvidence() {
  const [activeTrace, setActiveTrace] = useState<EvidenceTraceKey>("allow");
  const trace = evidenceTraces[activeTrace];

  return (
    <section className="border-t border-[#1A2744] bg-[#05080F] px-4 py-16 sm:px-6 sm:py-24">
      <div className="mx-auto max-w-5xl">
        <div className="mb-10 sm:mb-12">
          <p className="mb-4 font-mono text-xs uppercase tracking-[0.25em] text-[#7A90B4]">
            Live evidence
          </p>
          <h2 className="text-2xl font-light text-[#D8E4F4] sm:text-3xl">
            Every decision, permanently auditable.
          </h2>
          <p className="mt-4 max-w-3xl text-[15px] leading-relaxed text-[#7A90B4]">
            Real governance decisions. Every outcome is permanent. Every record is
            forensically reconstructible.
          </p>
        </div>

        <div className="overflow-hidden rounded-md border border-[#1A2744] bg-[#0B1120] p-5 font-mono text-sm sm:p-8">
          <div className="mb-6 flex flex-col gap-4 border-b border-[#1A2744] pb-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <motion.div
                animate={{ opacity: [1, 0.3, 1] }}
                transition={{ duration: 2, repeat: Infinity }}
                className="h-2 w-2 rounded-full bg-green-400/70"
              />
              <span className="break-all text-[11px] text-[#7A90B4] sm:text-xs">
                {trace.header}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(evidenceTraces) as EvidenceTraceKey[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveTrace(key)}
                  className={`rounded border px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] transition-colors ${
                    activeTrace === key
                      ? "border-[#C9A84C] bg-[#C9A84C]/10 text-[#D8E4F4]"
                      : "border-[#1A2744] text-[#7A90B4] hover:border-[#2A5CAA] hover:text-[#D8E4F4]"
                  }`}
                >
                  {evidenceTraces[key].label}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-4">
            {trace.rows.map((row, i) => (
              <motion.div
                key={`${trace.label}-${row.label}`}
                initial={{ opacity: 0, x: -8 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.06 }}
                className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-6"
              >
                <span className="w-full text-xs tracking-wider text-[#2A5CAA] sm:w-36 sm:shrink-0">
                  {row.label}
                </span>
                <span className={`${row.color} break-words`}>{row.value}</span>
                <span className="break-words text-xs text-[#7A90B4]/60">{row.accent}</span>
              </motion.div>
            ))}
          </div>
        </div>
        <p className="mt-3 font-mono text-xs text-[#7A90B4]">
          Real session. Real governance decision. Cryptographically signed. ·
          <a
            href="/trust/architecture"
            className="ml-1 text-[#2A5CAA] transition-colors hover:text-[#3D7DD4]"
          >
            Open security architecture →
          </a>
        </p>
      </div>
    </section>
  );
}
