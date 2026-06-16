"use client";

import { motion } from "framer-motion";
import { ArrowRight, Play } from "lucide-react";
import { GovernanceTraceConsole } from "./operious-graphics";

function KernelSealLogo({ className }: { className?: string }) {
  return (
    <motion.svg viewBox="0 0 280 280" fill="none" xmlns="http://www.w3.org/2000/svg" className={className} aria-hidden="true">
      <motion.path d="M140 20L240 70V180L140 260L40 180V70L140 20Z" stroke="#0A0F1C" strokeWidth="2" fill="none" initial={{ pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 1 }} transition={{ duration: 0.4, ease: "easeOut" }} />
      <motion.path d="M140 45L215 85V165L140 235L65 165V85L140 45Z" stroke="#1A2538" strokeWidth="1.5" fill="none" initial={{ pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 1 }} transition={{ duration: 0.4, ease: "easeOut", delay: 0.1 }} />
      <motion.path d="M140 70L190 100V150L140 210L90 150V100L140 70Z" stroke="#2A3548" strokeWidth="1" fill="none" initial={{ pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 1 }} transition={{ duration: 0.4, ease: "easeOut", delay: 0.2 }} />
      <motion.g initial={{ opacity: 0, scale: 0.92 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.5, delay: 0.7, ease: "easeOut" }}>
        <path d="M140 95L170 115V155L140 175L110 155V115L140 95Z" fill="#0A0F1C" stroke="#3A4558" strokeWidth="1" />
        <path d="M140 110L155 125V145L140 160L125 145V125L140 110Z" fill="#1A2538" />
        <circle cx="140" cy="135" r="6" fill="#0A0F1C" />
      </motion.g>
      <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4, delay: 1.0, ease: "easeOut" }}>
        <path d="M140 20L180 45" stroke="#A8882C" strokeWidth="2" strokeLinecap="round" />
        <path d="M140 20L100 45" stroke="#A8882C" strokeWidth="2" strokeLinecap="round" />
        <path d="M140 260L180 235" stroke="#A8882C" strokeWidth="2" strokeLinecap="round" />
        <path d="M140 260L100 235" stroke="#A8882C" strokeWidth="2" strokeLinecap="round" />
        <path d="M40 100L40 150" stroke="#A8882C" strokeWidth="2" strokeLinecap="round" />
        <path d="M240 100L240 150" stroke="#A8882C" strokeWidth="2" strokeLinecap="round" />
        <circle cx="140" cy="135" r="3" fill="#C9A84C" />
      </motion.g>
    </motion.svg>
  );
}

function AnimatedHeadline() {
  const words = ["Operational", "infrastructure", "that", "cannot"];
  const italicWord = "deviate.";

  const wordVariants = {
    hidden: { opacity: 0, y: 24 },
    visible: (i: number) => ({ opacity: 1, y: 0, transition: { duration: 0.6, delay: 1.1 + i * 0.08, ease: [0.22, 1, 0.36, 1] } }),
  };

  const italicVariants = {
    hidden: { opacity: 0, y: 24, scale: 0.96 },
    visible: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.8, delay: 1.1 + words.length * 0.08, ease: [0.22, 1, 0.36, 1] } },
  };

  return (
    <h1 className="text-[40px] font-bold leading-[1.05] tracking-[-0.02em] text-[#D8E4F4] sm:text-[56px] md:text-[72px] lg:text-[84px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>
      {words.map((word, i) => (
        <motion.span key={word} custom={i} initial="hidden" animate="visible" variants={wordVariants} className="mr-[0.25em] inline-block">
          {word}
        </motion.span>
      ))}
      <motion.em initial="hidden" animate="visible" variants={italicVariants} className="inline-block tracking-[-0.01em]" style={{ fontFamily: "var(--font-cormorant)", fontStyle: "italic" }}>
        {italicWord}
      </motion.em>
    </h1>
  );
}

export function Hero() {
  return (
    <section className="relative flex min-h-[720px] items-center overflow-hidden bg-[#05080F] lg:min-h-screen">
      <div className="absolute inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute left-0 top-0 h-[60%] w-[60%]" style={{ background: "radial-gradient(ellipse at top left, rgba(168, 136, 44, 0.06) 0%, transparent 40%)" }} />
        <div className="absolute bottom-0 right-0 h-[60%] w-[60%]" style={{ background: "radial-gradient(ellipse at bottom right, rgba(26, 74, 154, 0.08) 0%, transparent 40%)" }} />
        <div className="absolute inset-0 opacity-[0.04]" style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='52' viewBox='0 0 60 52' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 0L60 15V37L30 52L0 37V15L30 0Z' fill='none' stroke='%23ffffff' stroke-width='0.5'/%3E%3C/svg%3E")`, backgroundSize: "60px 52px" }} />
      </div>

      <div className="relative z-10 mx-auto w-full max-w-[1440px] px-4 pb-16 pt-[88px] sm:px-6 lg:px-16 lg:pb-24">
        <div className="grid items-center gap-10 lg:grid-cols-[0.95fr_1.05fr] lg:gap-16">
          <div className="flex flex-col gap-6 text-center lg:text-left">
            <div className="flex lg:hidden items-center justify-center mb-4">
              <KernelSealLogo className="h-[160px] w-[160px] sm:h-[200px] sm:w-[200px]" />
            </div>
            <motion.p initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.4, delay: 1.1, ease: "easeOut" }} className="text-[10px] uppercase tracking-[0.18em] text-[#C9A84C] sm:text-[11px]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>
              Operational Infrastructure · v1.0
            </motion.p>
            <AnimatedHeadline />
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 1.8, ease: "easeOut" }} className="mx-auto max-w-[560px] text-[16px] font-normal leading-[1.55] tracking-[-0.011em] text-[#7A90B4] sm:text-[18px] lg:mx-0 lg:text-[22px]">
              Operious AI is a deterministic execution substrate for enterprise operations. Every action is governed by mathematically enforced policy. Every decision is cryptographically reconstructible. Every outcome is inevitable.
            </motion.p>

            <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 2.1, ease: "easeOut" }} className="mt-2 flex flex-col items-center gap-3 sm:flex-row lg:items-start lg:justify-start">
              <a href="/demo" className="group inline-flex h-12 w-full items-center justify-center rounded-[14px] bg-[#C9A84C] px-6 text-[14px] font-semibold tracking-[-0.01em] text-[#05080F] transition-colors duration-[160ms] hover:bg-[#D4B85A] sm:w-auto sm:px-8 sm:text-[15px]">
                <span>Request Infrastructure Briefing</span>
                <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-1 sm:h-5 sm:w-5" />
              </a>
              <a href="/platform" className="group inline-flex h-12 w-full items-center justify-center rounded-[14px] border border-[#2A3548] px-6 text-[14px] font-medium tracking-[-0.01em] text-[#7A90B4] transition-colors duration-[160ms] hover:border-[#3A4558] hover:text-[#9AAFCC] sm:w-auto sm:px-8 sm:text-[15px]">
                <Play className="mr-2 h-4 w-4" />
                <span>Watch Platform Overview</span>
              </a>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay: 2.4, ease: "easeOut" }} className="mt-4 flex flex-wrap justify-center gap-2 lg:justify-start">
              {['Deterministic by design', 'Replay ready', 'Fail-closed by default'].map((chip) => (
                <span key={chip} className="rounded-full border border-[#24324a] bg-[#08111d]/70 px-3 py-1.5 text-[11px] uppercase tracking-[0.2em] text-[#7A90B4]">{chip}</span>
              ))}
            </motion.div>
          </div>

          <motion.div initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.7, delay: 1.4, ease: [0.16, 1, 0.3, 1] }} className="hidden lg:block">
            <GovernanceTraceConsole />
          </motion.div>
        </div>
      </div>
    </section>
  );
}
