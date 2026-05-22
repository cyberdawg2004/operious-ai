"use client";

import { useRef, useEffect, useState } from "react";
import { motion, useInView } from "framer-motion";

const stats = [
  {
    value: 1927,
    display: "1,927",
    isNumeric: true,
    description: "Deterministic invariant tests enforce the substrate doctrine.",
  },
  {
    value: 100,
    display: "100%",
    suffix: "%",
    isNumeric: true,
    description: "Replay fidelity for every operational decision.",
  },
  {
    value: 0,
    display: "Zero",
    isNumeric: false,
    description: "Substrate isolation violations across the codebase.",
  },
  {
    value: null,
    display: "UUID5",
    isNumeric: false,
    description: "Cryptographic identity for every event in lineage.",
  },
];

function useCountUp(
  end: number,
  duration: number,
  shouldStart: boolean
): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!shouldStart) return;

    let startTime: number | null = null;
    let animationFrame: number;

    const easeOutExpo = (t: number): number => {
      return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
    };

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

function StatCell({
  stat,
  index,
  inView,
}: {
  stat: (typeof stats)[0];
  index: number;
  inView: boolean;
}) {
  const count = useCountUp(
    stat.isNumeric && stat.value !== null ? stat.value : 0,
    1200,
    inView && stat.isNumeric && stat.value !== null && stat.value > 0
  );

  const formatNumber = (num: number) => {
    return num.toLocaleString("en-US");
  };

  const displayValue = () => {
    if (!stat.isNumeric) {
      return stat.display;
    }
    if (stat.value === 0) {
      return "Zero";
    }
    return `${formatNumber(count)}${stat.suffix || ""}`;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
      transition={{
        duration: 0.6,
        delay: index * 0.1,
        ease: [0.16, 1, 0.3, 1],
      }}
    >
      <div
        className="font-mono text-[80px] font-medium leading-none text-gold-bright"
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {displayValue()}
      </div>
      <p className="mt-6 max-w-[240px] font-serif-display text-[18px] italic leading-[1.4] text-[#D8E4F4]">
        {stat.description}
      </p>
    </motion.div>
  );
}

export function TrustProof() {
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-100px" });

  return (
    <section
      ref={sectionRef}
      className="relative bg-[#05080F] py-40 px-16"
    >
      {/* Atmospheric corner gradients */}
      <div
        className="pointer-events-none absolute inset-0 overflow-hidden"
        aria-hidden="true"
      >
        <div
          className="absolute -top-1/4 -left-1/4 h-[600px] w-[600px] rounded-full"
          style={{
            background:
              "radial-gradient(circle, rgba(168, 136, 44, 0.04) 0%, transparent 70%)",
          }}
        />
        <div
          className="absolute -bottom-1/4 -right-1/4 h-[600px] w-[600px] rounded-full"
          style={{
            background:
              "radial-gradient(circle, rgba(59, 130, 246, 0.04) 0%, transparent 70%)",
          }}
        />
      </div>

      <div className="relative mx-auto max-w-[1280px]">
        {/* Section header */}
        <div>
          <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-gold">
            §05 · GUARANTEES
          </span>
          <h2 className="mt-6 font-serif-display text-[64px] font-bold leading-[1.1] text-[#D8E4F4]">
            Mathematical guarantees,
            <br />
            not marketing claims.
          </h2>
        </div>

        {/* Four-column grid */}
        <div className="mt-24 grid grid-cols-2 gap-12 lg:grid-cols-4">
          {stats.map((stat, index) => (
            <StatCell key={index} stat={stat} index={index} inView={isInView} />
          ))}
        </div>

        {/* Pull quote */}
        <motion.div
          className="mx-auto mt-24 max-w-[800px] text-center"
          initial={{ opacity: 0, y: 16 }}
          animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }}
          transition={{
            duration: 0.6,
            delay: 1.4,
            ease: [0.16, 1, 0.3, 1],
          }}
        >
          <p className="font-serif-display text-[32px] italic font-medium leading-[1.4] text-gold">
            &ldquo;Determinism is the precondition for trust. We refuse to ship
            anything that cannot be reconstructed.&rdquo;
          </p>
        </motion.div>
      </div>
    </section>
  );
}
