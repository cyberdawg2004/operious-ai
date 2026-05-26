"use client";

import { motion } from "framer-motion";

const evidenceRows = [
  {
    label: "CLASSIFICATION",
    value: "charging_issue",
    accent: "0.93 confidence",
    color: "text-[#D8E4F4]",
  },
  {
    label: "GOVERNANCE",
    value: "ALLOW",
    accent: "anker_confidence_thresholds v1",
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
];

export function LiveEvidence() {
  return (
    <section className="border-t border-[#1A2744] px-6 py-24">
      <div className="mx-auto max-w-5xl">
        <div className="mb-12">
          <p className="mb-4 font-mono text-xs uppercase tracking-[0.25em] text-[#7A90B4]">
            Live evidence
          </p>
          <h2 className="text-3xl font-light text-[#D8E4F4]">
            Every decision, permanently auditable.
          </h2>
        </div>

        <div className="border border-[#1A2744] bg-[#0B1120] p-8 font-mono text-sm">
          <div className="mb-6 flex items-center gap-2 border-b border-[#1A2744] pb-4">
            <motion.div
              animate={{ opacity: [1, 0.3, 1] }}
              transition={{ duration: 2, repeat: Infinity }}
              className="h-2 w-2 rounded-full bg-green-400/70"
            />
            <span className="text-xs text-[#7A90B4]">
              anker-pilot · Session df6139ba · 2026-05-24T03:10:28Z · LIVE
            </span>
          </div>
          <div className="space-y-4">
            {evidenceRows.map((row, i) => (
              <motion.div
                key={row.label}
                initial={{ opacity: 0, x: -8 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.06 }}
                className="flex gap-6 items-baseline"
              >
                <span className="w-36 shrink-0 text-xs tracking-wider text-[#2A5CAA]">
                  {row.label}
                </span>
                <span className={row.color}>{row.value}</span>
                <span className="text-xs text-[#7A90B4]/60">{row.accent}</span>
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
            Read the architecture →
          </a>
        </p>
      </div>
    </section>
  );
}
