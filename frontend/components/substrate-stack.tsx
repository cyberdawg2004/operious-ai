"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { ArchitectureDiagram } from "./operious-graphics";

const layers = [
  { name: "GOVERNANCE", description: "Mathematical policy enforcement" },
  { name: "TOPOLOGY", description: "Authorized agent coordination pathways" },
  { name: "POLICY", description: "Capability-gated execution legality" },
  { name: "ARBITRATION", description: "Deterministic conflict resolution" },
  { name: "EXECUTION", description: "Claim-before-run worker sovereignty" },
  { name: "HARDENING", description: "Lineage, replay, and containment invariants" },
];

const guarantees = [
  { title: "Determinism", description: "Same inputs always yield same outputs, regardless of execution environment." },
  { title: "Traceability", description: "Every decision can be traced to its authorizing policy and input state." },
  { title: "Containment", description: "Agents cannot exceed their declared capability envelope under any circumstance." },
];

export function SubstrateStack() {
  const sectionRef = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: sectionRef, offset: ["start end", "end start"] });
  const lineHeight = useTransform(scrollYProgress, [0.1, 0.6], ["0%", "100%"]);

  return (
    <section ref={sectionRef} className="relative min-h-screen overflow-hidden bg-[#05080F] px-4 py-20 sm:px-8 sm:py-28 lg:px-16 lg:py-40">
      <div className="pointer-events-none absolute inset-0" style={{ background: `radial-gradient(ellipse 600px 400px at 0% 0%, rgba(168, 136, 44, 0.04), transparent 70%), radial-gradient(ellipse 600px 400px at 100% 100%, rgba(26, 74, 154, 0.04), transparent 70%)` }} />

      <div className="relative mx-auto max-w-[1280px]">
        <div className="mb-12 sm:mb-16 lg:mb-24">
          <p className="mb-3 font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-gold sm:mb-4 sm:text-[11px]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>§02 · THE KERNEL</p>
          <h2 className="mb-4 text-[36px] font-bold leading-[1.05] tracking-[-0.015em] text-[#D8E4F4] sm:mb-6 sm:text-[48px] lg:text-[64px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>An execution substrate, not a chatbot wrapper.</h2>
          <p className="max-w-[760px] text-[15px] leading-relaxed text-[#7A90B4] sm:text-[16px] lg:text-[18px]" style={{ fontFamily: "var(--font-geist-sans)" }}>Operious is built on a layered operational kernel. Each layer enforces a specific constitutional guarantee. Layers are isolated by mathematical contract, not convention. Violations break deployment, not runtime.</p>
        </div>

        <div className="grid grid-cols-1 gap-12 lg:grid-cols-[0.95fr_1.05fr] lg:gap-24">
          <div className="relative rounded-[32px] border border-[#24324a] bg-[rgba(9,15,25,0.9)] p-4 shadow-[0_24px_100px_rgba(0,0,0,0.25)] sm:p-6 lg:p-8">
            <div className="absolute bottom-0 left-8 top-0 w-[2px] overflow-hidden">
              <motion.div className="w-full origin-top" style={{ height: lineHeight, background: "linear-gradient(to bottom, #A8882C 0%, #1A4A9A 100%)" }} />
            </div>
            <div className="mb-6 flex items-center justify-between px-3">
              <p className="text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>system stack</p>
              <div className="rounded-full border border-[#24324a] bg-[#0b1321] px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-[#7A90B4]">governed layers</div>
            </div>
            <div className="flex flex-col gap-3 pl-6">
              {layers.map((layer, index) => (
                <motion.div key={layer.name} initial={{ opacity: 0, x: -20 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true, margin: "-50px" }} transition={{ delay: index * 0.08, duration: 0.45 }} className="flex min-h-[72px] w-full items-center justify-between rounded-[14px] border border-[#24324a] bg-[#0b1321] px-5 py-4">
                  <span className="font-mono text-[13px] font-medium uppercase tracking-[0.12em] text-[#D8E4F4]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>{layer.name}</span>
                  <span className="max-w-[240px] text-right text-[13px] leading-relaxed text-[#7A90B4]">{layer.description}</span>
                </motion.div>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-8">
            <ArchitectureDiagram />
            <div className="rounded-[28px] border border-[#24324a] bg-[rgba(9,15,25,0.9)] p-6 shadow-[0_24px_100px_rgba(0,0,0,0.2)]">
              <p className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-gold" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>CONSTITUTIONAL GUARANTEES</p>
              <div className="mt-6 space-y-5">
                {guarantees.map((guarantee, index) => (
                  <motion.div key={guarantee.title} initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-50px" }} transition={{ delay: index * 0.12, duration: 0.45 }} className="rounded-[16px] border border-[#24324a] bg-[#0b1321] p-4">
                    <h3 className="text-[20px] font-semibold tracking-[-0.01em] text-[#D8E4F4]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>{guarantee.title}</h3>
                    <p className="mt-2 text-[14px] leading-relaxed text-[#7A90B4]">{guarantee.description}</p>
                  </motion.div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
