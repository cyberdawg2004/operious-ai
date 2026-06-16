"use client";

import { useRef, useEffect, useState } from "react";
import { motion, useInView } from "framer-motion";
import { CommandCenterPreview } from "./operious-graphics";

const stats = [
  { value: 1927, display: "1,927", isNumeric: true, description: "Deterministic invariant tests enforce the substrate doctrine." },
  { value: 100, display: "100%", suffix: "%", isNumeric: true, description: "Replay fidelity for every operational decision." },
  { value: 0, display: "Zero", isNumeric: false, description: "Substrate isolation violations across the codebase." },
  { value: null, display: "UUID5", isNumeric: false, description: "Cryptographic identity for every event in lineage." },
];

function useCountUp(end: number, duration: number, shouldStart: boolean): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!shouldStart) return;

    let startTime: number | null = null;
    let animationFrame: number;

    const easeOutExpo = (t: number): number => t === 1 ? 1 : 1 - Math.pow(2, -10 * t);

    const animate = (currentTime: number) => {
      if (startTime === null) startTime = currentTime;
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easeOutExpo(progress);
      setCount(Math.floor(easedProgress * end));

      if (progress < 1) {
        animationFrame = requestAnimationFrame(animate);
      } else {
        setCount(end);
      }
    };

    animationFrame = requestAnimationFrame(animate);

    return () => {
      if (animationFrame) cancelAnimationFrame(animationFrame);
    };
  }, [end, duration, shouldStart]);

  return count;
}

function StatCell({ stat, index, inView }: { stat: (typeof stats)[0]; index: number; inView: boolean }) {
  const count = useCountUp(stat.isNumeric && stat.value !== null ? stat.value : 0, 1200, inView && stat.isNumeric && stat.value !== null && stat.value > 0);
  const formatNumber = (num: number) => num.toLocaleString("en-US");
  const displayValue = () => {
    if (!stat.isNumeric) return stat.display;
    if (stat.value === 0) return "Zero";
    return `${formatNumber(count)}${stat.suffix || ""}`;
  };

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }} transition={{ duration: 0.6, delay: index * 0.1, ease: [0.16, 1, 0.3, 1] }} className="rounded-[24px] border border-[#24324a] bg-[rgba(8,14,24,0.86)] p-6 shadow-[0_20px_70px_rgba(0,0,0,0.16)]">
      <div className="font-mono text-[48px] font-medium leading-none text-gold-bright sm:text-[60px] lg:text-[80px]" style={{ fontVariantNumeric: "tabular-nums", fontFamily: "var(--font-ibm-plex-mono)" }}>{displayValue()}</div>
      <p className="mt-4 max-w-[240px] text-[15px] italic leading-[1.4] text-[#D8E4F4] sm:mt-6 sm:text-[16px] lg:text-[18px]" style={{ fontFamily: "var(--font-cormorant)" }}>{stat.description}</p>
    </motion.div>
  );
}

export function TrustProof() {
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-100px" });

  return (
    <section ref={sectionRef} className="relative overflow-hidden bg-[#05080F] px-4 py-20 sm:px-8 sm:py-28 lg:px-16 lg:py-40">
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute -left-1/4 -top-1/4 h-[600px] w-[600px] rounded-full" style={{ background: "radial-gradient(circle, rgba(168, 136, 44, 0.04) 0%, transparent 70%)" }} />
        <div className="absolute -bottom-1/4 -right-1/4 h-[600px] w-[600px] rounded-full" style={{ background: "radial-gradient(circle, rgba(59, 130, 246, 0.04) 0%, transparent 70%)" }} />
      </div>

      <div className="relative mx-auto max-w-[1280px]">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-gold sm:text-[11px]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>§05 · GUARANTEES</span>
            <h2 className="mt-4 text-[36px] font-bold leading-[1.1] text-[#D8E4F4] sm:mt-6 sm:text-[48px] lg:text-[64px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>Mathematical guarantees,<br className="hidden sm:block" />not marketing claims.</h2>
          </div>
          <p className="max-w-[430px] text-[15px] leading-relaxed text-[#7A90B4] sm:text-[16px]">Governance is enforced at runtime, audited post-event, and replayable for compliance teams without human reconstruction.</p>
        </div>

        <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-[0.95fr_1.05fr] lg:mt-16">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            {stats.map((stat, index) => (<StatCell key={index} stat={stat} index={index} inView={isInView} />))}
          </div>
          <motion.div initial={{ opacity: 0, y: 16 }} animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }} transition={{ duration: 0.6, delay: 0.9, ease: [0.16, 1, 0.3, 1] }}>
            <CommandCenterPreview />
          </motion.div>
        </div>

        <motion.div className="mx-auto mt-12 max-w-[800px] px-4 text-center sm:mt-16 lg:mt-24" initial={{ opacity: 0, y: 16 }} animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }} transition={{ duration: 0.6, delay: 1.4, ease: [0.16, 1, 0.3, 1] }}>
          <p className="text-[24px] font-medium italic leading-[1.4] text-gold sm:text-[28px] lg:text-[32px]" style={{ fontFamily: "var(--font-cormorant)" }}>&ldquo;Determinism is the precondition for trust. We refuse to ship anything that cannot be reconstructed.&rdquo;</p>
        </motion.div>
      </div>
    </section>
  );
}
