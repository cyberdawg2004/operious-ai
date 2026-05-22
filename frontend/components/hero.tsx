"use client";

import { motion } from "framer-motion";
import { ArrowRight, Play } from "lucide-react";

// Animated KernelSeal Logo with three-phase entry
function KernelSealLogo() {
  return (
    <motion.svg
      width="280"
      height="280"
      viewBox="0 0 280 280"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="relative"
      style={{ marginTop: "-20px" }} // Optical compensation
    >
      {/* Outer hexagon - Phase 1: stroke draw animation */}
      <motion.path
        d="M140 20L240 70V180L140 260L40 180V70L140 20Z"
        stroke="#0A0F1C"
        strokeWidth="2"
        fill="none"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
      />
      
      {/* Second hexagon ring */}
      <motion.path
        d="M140 45L215 85V165L140 235L65 165V85L140 45Z"
        stroke="#1A2538"
        strokeWidth="1.5"
        fill="none"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.4, ease: "easeOut", delay: 0.1 }}
      />
      
      {/* Third hexagon ring */}
      <motion.path
        d="M140 70L190 100V150L140 210L90 150V100L140 70Z"
        stroke="#2A3548"
        strokeWidth="1"
        fill="none"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.4, ease: "easeOut", delay: 0.2 }}
      />

      {/* Inner glyph - Phase 2: fade and scale */}
      <motion.g
        initial={{ opacity: 0, scale: 0.92 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, delay: 0.7, ease: "easeOut" }}
      >
        {/* Central kernel shape */}
        <path
          d="M140 95L170 115V155L140 175L110 155V115L140 95Z"
          fill="#0A0F1C"
          stroke="#3A4558"
          strokeWidth="1"
        />
        {/* Inner diamond */}
        <path
          d="M140 110L155 125V145L140 160L125 145V125L140 110Z"
          fill="#1A2538"
        />
        {/* Center dot */}
        <circle cx="140" cy="135" r="6" fill="#0A0F1C" />
      </motion.g>

      {/* Gold accent strokes - Phase 3: illuminate */}
      <motion.g
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4, delay: 1.0, ease: "easeOut" }}
      >
        {/* Top accent */}
        <path
          d="M140 20L180 45"
          stroke="#A8882C"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <path
          d="M140 20L100 45"
          stroke="#A8882C"
          strokeWidth="2"
          strokeLinecap="round"
        />
        {/* Bottom accent */}
        <path
          d="M140 260L180 235"
          stroke="#A8882C"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <path
          d="M140 260L100 235"
          stroke="#A8882C"
          strokeWidth="2"
          strokeLinecap="round"
        />
        {/* Side accents */}
        <path
          d="M40 100L40 150"
          stroke="#A8882C"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <path
          d="M240 100L240 150"
          stroke="#A8882C"
          strokeWidth="2"
          strokeLinecap="round"
        />
        {/* Inner glow dots */}
        <circle cx="140" cy="135" r="3" fill="#C9A84C" />
      </motion.g>
    </motion.svg>
  );
}

// Animated headline with word-by-word animation
function AnimatedHeadline() {
  const words = ["Operational", "infrastructure", "that", "cannot"];
  const italicWord = "deviate.";
  
  const wordVariants = {
    hidden: { opacity: 0, y: 24 },
    visible: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.6,
        delay: 1.1 + i * 0.08,
        ease: [0.22, 1, 0.36, 1],
      },
    }),
  };

  const italicVariants = {
    hidden: { opacity: 0, y: 24, scale: 0.96 },
    visible: {
      opacity: 1,
      y: 0,
      scale: 1,
      transition: {
        duration: 0.8,
        delay: 1.1 + words.length * 0.08,
        ease: [0.22, 1, 0.36, 1],
      },
    },
  };

  return (
    <h1
      className="text-[88px] font-bold leading-[1.05] tracking-[-0.02em] text-[#D8E4F4] max-w-[760px]"
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
      className="relative min-h-[720px] h-screen flex items-center"
      style={{ backgroundColor: "#05080F" }}
    >
      {/* Atmospheric background - CSS only */}
      <div className="absolute inset-0 overflow-hidden">
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
      <div className="relative z-10 w-full max-w-[1440px] mx-auto px-16 pt-[72px]">
        {/* Two-column grid */}
        <div className="grid grid-cols-[40%_60%] gap-24 items-center">
          {/* LEFT COLUMN - Logo */}
          <div className="flex items-center justify-center">
            <KernelSealLogo />
          </div>

          {/* RIGHT COLUMN - Content */}
          <div className="flex flex-col gap-8">
            {/* Eyebrow label */}
            <motion.p
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.4, delay: 1.1, ease: "easeOut" }}
              className="text-[11px] uppercase tracking-[0.18em] text-[#C9A84C]"
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
              className="text-[22px] font-normal leading-[1.55] tracking-[-0.011em] text-[#7A90B4] max-w-[540px]"
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
              className="flex items-center gap-4 mt-4"
            >
              {/* Primary CTA */}
              <a
                href="/demo"
                className="group inline-flex items-center justify-center h-14 px-8 text-[15px] font-semibold tracking-[-0.01em] text-[#05080F] bg-[#C9A84C] rounded-md hover:bg-[#D4B85A] transition-colors"
              >
                <span>Request Infrastructure Briefing</span>
                <ArrowRight className="ml-2 w-5 h-5 transition-transform group-hover:translate-x-1" />
              </a>

              {/* Secondary CTA */}
              <a
                href="/platform"
                className="group inline-flex items-center justify-center h-14 px-8 text-[15px] font-medium tracking-[-0.01em] text-[#7A90B4] border border-[#2A3548] rounded-md hover:border-[#3A4558] hover:text-[#9AAFCC] transition-colors"
              >
                <Play className="mr-2 w-4 h-4" />
                <span>Watch Platform Overview</span>
              </a>
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  );
}
