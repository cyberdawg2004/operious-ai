"use client";

import { motion, useReducedMotion } from "framer-motion";
import { KernelSeal } from "@/components/kernel-seal";

export function HeroVisual() {
  const reducedMotion = useReducedMotion();

  return (
    <div className="relative mx-auto flex min-h-[420px] w-full max-w-[520px] items-center justify-center overflow-hidden py-6 lg:justify-end">
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
      <div className="absolute inset-10 rounded-full border border-[#1A2744]" />
      <motion.div
        className="relative z-10"
        animate={reducedMotion ? undefined : { y: [0, -8, 0] }}
        transition={{ duration: 6.5, repeat: Infinity, ease: "easeInOut" }}
      >
        <KernelSeal size={250} phase={3} />
      </motion.div>
    </div>
  );
}
