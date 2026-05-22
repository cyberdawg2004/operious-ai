"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";

const layers = [
  { name: "GOVERNANCE", description: "Mathematical policy enforcement" },
  { name: "TOPOLOGY", description: "Authorized agent coordination pathways" },
  { name: "POLICY", description: "Capability-gated execution legality" },
  { name: "ARBITRATION", description: "Deterministic conflict resolution" },
  { name: "EXECUTION", description: "Claim-before-run worker sovereignty" },
  { name: "HARDENING", description: "Lineage, replay, and containment invariants" },
];

const guarantees = [
  {
    title: "Determinism",
    description: "Same inputs always yield same outputs, regardless of execution environment.",
  },
  {
    title: "Traceability",
    description: "Every decision can be traced to its authorizing policy and input state.",
  },
  {
    title: "Containment",
    description: "Agents cannot exceed their declared capability envelope under any circumstance.",
  },
];

export function SubstrateStack() {
  const sectionRef = useRef<HTMLElement>(null);
  const stackRef = useRef<HTMLDivElement>(null);

  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ["start end", "end start"],
  });

  // Line draws from 0 to 100% as section scrolls into view
  const lineHeight = useTransform(scrollYProgress, [0.1, 0.6], ["0%", "100%"]);

  return (
    <section
      ref={sectionRef}
      className="relative min-h-screen py-40 px-16 bg-[#05080F]"
    >
      {/* Atmospheric gradients */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: `
            radial-gradient(ellipse 600px 400px at 0% 0%, rgba(168, 136, 44, 0.04), transparent 70%),
            radial-gradient(ellipse 600px 400px at 100% 100%, rgba(26, 74, 154, 0.04), transparent 70%)
          `,
        }}
      />

      <div className="relative mx-auto max-w-[1280px]">
        {/* Section Header */}
        <div className="mb-24">
          <p
            className="mb-4 font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-gold"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            §02 · THE KERNEL
          </p>
          <h2
            className="mb-6 text-[64px] font-bold leading-[1.05] tracking-[-0.015em] text-[#D8E4F4]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            An execution substrate, not a chatbot wrapper.
          </h2>
          <p
            className="max-w-[760px] text-[18px] leading-relaxed text-[#7A90B4]"
            style={{ fontFamily: "var(--font-geist-sans)" }}
          >
            Operious is built on a layered operational kernel. Each layer
            enforces a specific constitutional guarantee. Layers are isolated by
            mathematical contract, not convention. Violations break deployment,
            not runtime.
          </p>
        </div>

        {/* Two Column Layout */}
        <div className="grid grid-cols-[60%_40%] gap-24">
          {/* Left Column - Stack Visualization */}
          <div ref={stackRef} className="relative">
            {/* Animated vertical line */}
            <div className="absolute left-0 top-0 bottom-0 w-[2px] overflow-hidden">
              <motion.div
                className="w-full origin-top"
                style={{
                  height: lineHeight,
                  background: "linear-gradient(to bottom, #A8882C 0%, #1A4A9A 100%)",
                }}
              />
            </div>

            {/* Layer Cards */}
            <div className="flex flex-col gap-3 pl-6">
              {layers.map((layer, index) => (
                <motion.div
                  key={layer.name}
                  initial={{ opacity: 0, x: -20 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, margin: "-50px" }}
                  transition={{ delay: index * 0.1, duration: 0.5 }}
                  className="flex h-20 w-full items-center justify-between rounded-lg border border-[#1A2744] bg-[#0B1120] px-6"
                >
                  <span
                    className="font-mono text-[14px] font-medium uppercase tracking-[0.12em] text-[#D8E4F4]"
                    style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
                  >
                    {layer.name}
                  </span>
                  <span
                    className="text-[14px] text-[#7A90B4]"
                    style={{ fontFamily: "var(--font-geist-sans)" }}
                  >
                    {layer.description}
                  </span>
                </motion.div>
              ))}
            </div>
          </div>

          {/* Right Column - Guarantees */}
          <div className="flex flex-col gap-10">
            <p
              className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              CONSTITUTIONAL GUARANTEES
            </p>

            {guarantees.map((guarantee, index) => (
              <motion.div
                key={guarantee.title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-50px" }}
                transition={{ delay: index * 0.15, duration: 0.5 }}
                className="flex flex-col gap-2"
              >
                <h3
                  className="text-[20px] font-semibold tracking-[-0.01em] text-[#D8E4F4]"
                  style={{ fontFamily: "var(--font-cormorant-sc)" }}
                >
                  {guarantee.title}
                </h3>
                <p
                  className="text-[14px] leading-relaxed text-[#7A90B4]"
                  style={{ fontFamily: "var(--font-geist-sans)" }}
                >
                  {guarantee.description}
                </p>
              </motion.div>
            ))}

            {/* Decorative hexagon */}
            <div className="mt-6">
              <svg
                width="64"
                height="64"
                viewBox="0 0 64 64"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M32 4L58 18V46L32 60L6 46V18L32 4Z"
                  stroke="#1A2744"
                  strokeWidth="1"
                  fill="none"
                />
                <path
                  d="M32 12L50 22V42L32 52L14 42V22L32 12Z"
                  stroke="#A8882C"
                  strokeWidth="1"
                  strokeOpacity="0.4"
                  fill="none"
                />
                <circle cx="32" cy="32" r="4" fill="#A8882C" fillOpacity="0.6" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
