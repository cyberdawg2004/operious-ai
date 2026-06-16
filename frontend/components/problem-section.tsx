"use client";

import { motion } from "framer-motion";

function WarningHexagon() {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M24 2L44 13.5V36.5L24 48L4 36.5V13.5L24 2Z" stroke="#A8882C" strokeWidth="1.5" fill="none" />
      <path d="M24 14L34 32H14L24 14Z" stroke="#A8882C" strokeWidth="1.5" fill="none" strokeLinejoin="round" />
      <line x1="24" y1="20" x2="24" y2="26" stroke="#A8882C" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="24" cy="29" r="1" fill="#A8882C" />
    </svg>
  );
}

function ConcentricHexagons() {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M24 2L44 13.5V36.5L24 48L4 36.5V13.5L24 2Z" stroke="#A8882C" strokeWidth="1.5" fill="none" />
      <path d="M24 10L36 17.5V32.5L24 40L12 32.5V17.5L24 10Z" stroke="#A8882C" strokeWidth="1.5" fill="none" opacity="0.6" />
      <path d="M24 17L30 21V31L24 35L18 31V21L24 17Z" stroke="#A8882C" strokeWidth="1.5" fill="none" opacity="0.3" />
    </svg>
  );
}

function FracturedChainHexagon() {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M24 2L44 13.5V36.5L24 48L4 36.5V13.5L24 2Z" stroke="#A8882C" strokeWidth="1.5" fill="none" />
      <rect x="10" y="20" width="10" height="8" rx="4" stroke="#A8882C" strokeWidth="1.5" fill="none" />
      <rect x="28" y="20" width="10" height="8" rx="4" stroke="#A8882C" strokeWidth="1.5" fill="none" />
      <line x1="20" y1="24" x2="22" y2="22" stroke="#A8882C" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="26" y1="26" x2="28" y2="24" stroke="#A8882C" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

const columns = [
  { icon: WarningHexagon, subtitle: "Workflows that improvise create liability.", body: "Language models trained to be helpful will exceed authorized parameters under pressure — granting refunds beyond limit, approving exceptions outside policy, generating communications that contradict legal guidance. Every helpful improvisation is an unaudited deviation from your operational contract.", resolution: "Operious agents cannot improvise. Behavior is locked to encoded governance." },
  { icon: ConcentricHexagons, subtitle: "Outputs that hallucinate erode confidence.", body: "Generative systems produce plausible-sounding but factually incorrect outputs at unpredictable intervals. In customer-facing operations, a single hallucinated policy statement or fabricated case history can trigger regulatory scrutiny, legal exposure, and irreversible reputational damage.", resolution: "Operious outputs are deterministic. Every response traces to verified source." },
  { icon: FracturedChainHexagon, subtitle: "Decisions that cannot be explained cannot be defended.", body: "When a regulatory body or legal proceeding demands explanation for an automated decision, 'the model thought it was right' is not a defensible answer. Black-box AI creates institutional risk that compounds with every unlogged interaction.", resolution: "Operious decisions are fully attributable. Every action has a compliance trail." },
];

const containerVariants = { hidden: { opacity: 0 }, visible: { opacity: 1, transition: { staggerChildren: 0.15 } } };
const itemVariants = { hidden: { opacity: 0, y: 24 }, visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] } } };

export function ProblemSection() {
  return (
    <section className="bg-[#f5efe4] px-4 py-20 sm:px-8 sm:py-28 lg:px-16 lg:py-40">
      <div className="mx-auto max-w-[1280px] rounded-[36px] border border-[#e7dfcf] bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(248,242,232,0.96))] p-6 shadow-[0_24px_80px_rgba(5,8,15,0.08)] sm:p-8 lg:p-12">
        <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-100px" }} transition={{ duration: 0.6 }}>
          <p className="mb-4 font-mono text-[10px] uppercase tracking-[0.18em] text-gold sm:mb-6 sm:text-[11px]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>§01 · THE PROBLEM</p>
          <h2 className="mb-6 max-w-[880px] text-[36px] font-bold leading-[1.08] tracking-[-0.015em] text-ink-primary sm:text-[48px] lg:text-[64px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>
            Enterprise operations were never built for autonomy.
          </h2>
          <p className="mb-10 max-w-[760px] text-[15px] leading-[1.55] text-ink-body sm:mb-14 sm:text-[16px] lg:mb-16 lg:text-[18px]">
            For decades, mission-critical operational workflows have depended on human improvisation, undocumented knowledge, and audit trails that exist only in case management software. Generative AI promised automation but introduced three new failure modes that are structurally incompatible with regulated enterprise environments.
          </p>
        </motion.div>

        <motion.div className="grid grid-cols-1 items-start gap-6 md:grid-cols-2 lg:grid-cols-3" variants={containerVariants} initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}>
          {columns.map((column, index) => {
            const IconComponent = column.icon;
            return (
              <motion.div key={index} variants={itemVariants} className="group relative overflow-hidden rounded-[24px] border border-[#e7dfcf] bg-[rgba(255,255,255,0.82)] p-7 transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_18px_60px_rgba(5,8,15,0.1)] sm:p-8">
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(168,136,44,0.1),transparent_45%)] opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                <div className="relative">
                  <div className="h-[48px] w-[48px]">
                    <IconComponent />
                  </div>
                  <h3 className="mt-6 mb-4 text-[22px] font-semibold leading-[1.25] tracking-[-0.005em] text-ink-primary sm:text-[24px] lg:text-[28px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>
                    {column.subtitle}
                  </h3>
                  <p className="mb-6 text-[14px] leading-[1.6] text-ink-body sm:text-[15px] lg:text-[16px]">{column.body}</p>
                  <p className="flex items-center gap-2 text-[14px] italic text-gold" style={{ fontFamily: "var(--font-cormorant)" }}>
                    <span className="h-[6px] w-[6px] flex-shrink-0 rounded-full bg-gold" />
                    {column.resolution}
                  </p>
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      </div>
    </section>
  );
}
