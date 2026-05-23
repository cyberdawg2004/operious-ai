"use client";

import { motion, type Variants } from "framer-motion";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { KernelSeal } from "./kernel-seal";

// Animated headline with word-by-word animation
function AnimatedHeadline() {
  const words = ["Governed", "execution", "infrastructure", "for"];
  const italicWord = "regulated operations.";

  const wordVariants: Variants = {
    hidden: { opacity: 0, y: 24 },
    visible: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.6,
        delay: 1.1 + i * 0.08,
        ease: "easeOut",
      },
    }),
  };

  const italicVariants: Variants = {
    hidden: { opacity: 0, y: 24, scale: 0.96 },
    visible: {
      opacity: 1,
      y: 0,
      scale: 1,
      transition: {
        duration: 0.8,
        delay: 1.1 + words.length * 0.08,
        ease: "easeOut",
      },
    },
  };

  return (
    <h1
      className="text-[40px] sm:text-[56px] md:text-[72px] lg:text-[88px] font-bold leading-[1.05] tracking-[-0.02em] text-[#D8E4F4]"
      style={{ fontFamily: "var(--font-cormorant-sc)" }}
    >
      {words.map((word, i) => (
        <motion.span
          key={word}
          custom={i}
          initial="hidden"
          animate="visible"
          variants={wordVariants}
          className="inline-block mr-[0.25em]"
        >
          {word}
        </motion.span>
      ))}
      <motion.em
        initial="hidden"
        animate="visible"
        variants={italicVariants}
        className="inline-block tracking-[-0.01em]"
        style={{ fontFamily: "var(--font-cormorant)", fontStyle: "italic" }}
      >
        {italicWord}
      </motion.em>
    </h1>
  );
}

export function Hero() {
  return (
    <section
      className="relative min-h-[720px] lg:min-h-screen flex items-center"
      style={{ backgroundColor: "#05080F" }}
    >
      {/* Atmospheric background - CSS only */}
      <div className="absolute inset-0 overflow-hidden" aria-hidden="true">
        {/* Radial gradient top-left (gold) */}
        <div
          className="absolute top-0 left-0 w-[60%] h-[60%]"
          style={{
            background:
              "radial-gradient(ellipse at top left, rgba(168, 136, 44, 0.04) 0%, transparent 40%)",
          }}
        />
        {/* Radial gradient bottom-right (blue) */}
        <div
          className="absolute bottom-0 right-0 w-[60%] h-[60%]"
          style={{
            background:
              "radial-gradient(ellipse at bottom right, rgba(26, 74, 154, 0.04) 0%, transparent 40%)",
          }}
        />
        {/* Hexagonal SVG pattern overlay */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='52' viewBox='0 0 60 52' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 0L60 15V37L30 52L0 37V15L30 0Z' fill='none' stroke='%23ffffff' stroke-width='0.5'/%3E%3C/svg%3E")`,
            backgroundSize: "60px 52px",
          }}
        />
      </div>

      {/* Container */}
      <div className="relative z-10 w-full max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-16 pt-[72px]">
        {/* Two-column grid - stacks on mobile */}
        <div className="grid grid-cols-1 lg:grid-cols-[40%_60%] gap-12 lg:gap-24 items-center py-12 lg:py-0">
          {/* LEFT COLUMN - Logo (hidden on mobile, shown in background) */}
          <div className="hidden lg:flex items-center justify-center">
            <KernelSeal size={280} phase={3} className="-mt-5" />
          </div>

          {/* Mobile Logo - smaller, centered above content */}
          <div className="flex lg:hidden items-center justify-center mb-8">
            <KernelSeal size={160} phase={3} className="sm:w-[200px] sm:h-[200px]" />
          </div>

          {/* RIGHT COLUMN - Content */}
          <div className="flex flex-col gap-6 lg:gap-8 text-center lg:text-left">
            {/* Eyebrow label */}
            <motion.p
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.4, delay: 1.1, ease: "easeOut" }}
              className="text-[10px] sm:text-[11px] uppercase tracking-[0.18em] text-[#C9A84C]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              Operational Infrastructure · v1.0
            </motion.p>

            {/* Headline */}
            <AnimatedHeadline />

            {/* Subhead */}
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.5, delay: 1.8, ease: "easeOut" }}
              className="text-[16px] sm:text-[18px] lg:text-[22px] font-normal leading-[1.55] tracking-[-0.011em] text-[#7A90B4] max-w-[540px] mx-auto lg:mx-0"
            >
              Operious AI is a deterministic execution substrate for enterprise
              operations. Every action is governed by mathematically enforced
              policy. Every decision is cryptographically reconstructible. Every
              outcome is inevitable.
            </motion.p>

            {/* CTA Buttons */}
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 2.1, ease: "easeOut" }}
              className="flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-3 sm:gap-4 mt-4"
            >
              {/* Primary CTA - Request Enterprise Access */}
              <Link
                href="/company/contact"
                className="group inline-flex items-center justify-center w-full sm:w-auto h-12 sm:h-14 px-6 sm:px-8 text-[14px] sm:text-[15px] font-semibold tracking-[-0.01em] text-[#05080F] bg-[#C9A84C] rounded-md hover:bg-[#D4B85A] transition-colors duration-[160ms]"
              >
                <span>Request Enterprise Access</span>
                <ArrowRight className="ml-2 w-4 sm:w-5 h-4 sm:h-5 transition-transform group-hover:translate-x-1" />
              </Link>

              {/* Secondary CTA - Read the architecture */}
              <Link
                href="/platform"
                className="group inline-flex items-center justify-center w-full sm:w-auto h-12 sm:h-14 px-6 sm:px-8 text-[14px] sm:text-[15px] font-medium tracking-[-0.01em] text-[#7A90B4] hover:text-[#C9A84C] transition-colors duration-[160ms]"
              >
                <span>Read the architecture</span>
                <ArrowRight className="ml-1.5 w-4 h-4 transition-transform group-hover:translate-x-1" />
              </Link>
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  );
}
