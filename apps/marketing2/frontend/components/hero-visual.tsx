"use client";

import { motion, useReducedMotion } from "framer-motion";
import { KernelSeal } from "@/components/kernel-seal";

export function HeroVisual() {
  const reducedMotion = useReducedMotion();
  const orbitDots = [0, 90, 180, 270];

  return (
    <div className="relative mx-auto flex min-h-[480px] w-full max-w-[560px] items-center justify-center overflow-hidden py-6">
      <motion.div
        className="absolute inset-x-10 top-10 h-px bg-gradient-to-r from-transparent via-[#2A5CAA]/70 to-transparent"
        animate={reducedMotion ? undefined : { opacity: [0.18, 0.7, 0.18] }}
        transition={{ duration: 4.5, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute bottom-16 left-8 right-8 h-px bg-gradient-to-r from-transparent via-[#C9A84C]/50 to-transparent"
        animate={reducedMotion ? undefined : { opacity: [0.12, 0.55, 0.12] }}
        transition={{ duration: 5.6, repeat: Infinity, ease: "easeInOut" }}
      />
      <div className="absolute inset-0 rounded-full bg-[#2A5CAA]/10 blur-3xl" />
      <motion.div
        animate={reducedMotion ? undefined : { rotate: 360 }}
        transition={{ duration: 80, repeat: Infinity, ease: "linear" }}
        className="absolute h-[440px] w-[440px] rounded-full border border-[#2A5CAA]/10"
      >
        {orbitDots.map((angle) => (
          <span
            key={angle}
            className="absolute left-1/2 top-1/2 h-2 w-2 rounded-full bg-[#A8882C] shadow-[0_0_18px_rgba(168,136,44,0.65)]"
            style={{
              transform: `rotate(${angle}deg) translateX(220px) translate(-50%, -50%)`,
            }}
          />
        ))}
      </motion.div>
      <motion.div
        animate={reducedMotion ? undefined : { rotate: -360 }}
        transition={{ duration: 55, repeat: Infinity, ease: "linear" }}
        className="absolute h-[340px] w-[340px] rounded-full border border-[#A8882C]/10"
      />
      <motion.div
        animate={reducedMotion ? undefined : { rotate: 360 }}
        transition={{ duration: 35, repeat: Infinity, ease: "linear" }}
        className="absolute h-[240px] w-[240px] rounded-full border border-[#2A5CAA]/15"
      />
      <motion.div
        className="relative z-10"
        animate={reducedMotion ? undefined : { y: [0, -8, 0] }}
        transition={{ duration: 6.5, repeat: Infinity, ease: "easeInOut" }}
      >
        <KernelSeal size={350} phase={3} />
      </motion.div>
    </div>
  );
}
