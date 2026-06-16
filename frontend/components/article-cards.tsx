"use client";

import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";

const articles = [
  { meta: "ENGINEERING · ARCHITECTURE", title: "Why Empty Policy Chains Must Return Deny.", excerpt: "The structural reason fail-closed governance is the only honest default for autonomous systems.", readingTime: "9 min read" },
  { meta: "DOCTRINE · OPERATIONS", title: "The Difference Between Throughput and Determinism.", excerpt: "Operations leaders are still optimizing the wrong variable.", readingTime: "12 min read" },
  { meta: "ENGINEERING · REPLAY", title: "Cryptographic Lineage Without Cryptographic Overhead.", excerpt: "How UUID5-based identity chains achieve tamper-evidence without the latency penalty of hash chaining.", readingTime: "7 min read" },
];

export function ArticleCards() {
  return (
    <section className="bg-[#f5efe4] px-4 py-20 sm:px-8 sm:py-28 lg:px-16 lg:py-40">
      <div className="mx-auto max-w-[1280px]">
        <div className="mb-12 sm:mb-16">
          <span className="mb-3 block font-mono text-[10px] uppercase tracking-[0.18em] text-gold sm:mb-4 sm:text-[11px]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>§07 · WRITING</span>
          <h2 className="mb-4 text-[36px] font-bold leading-[1.1] text-ink-primary sm:mb-6 sm:text-[48px] lg:text-[64px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>Operational substrate thinking.</h2>
          <p className="max-w-[760px] text-[15px] leading-relaxed text-ink-body sm:text-[16px] lg:text-[18px]">Long-form editorial on governed AI execution, operational doctrine, and the engineering discipline behind deterministic infrastructure.</p>
        </div>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 lg:gap-8">
          {articles.map((article, index) => (
            <motion.article key={index} className="group flex cursor-pointer flex-col gap-3 rounded-[24px] border border-[#e7dfcf] bg-[rgba(255,255,255,0.9)] p-6 shadow-[0_12px_40px_rgba(5,8,15,0.06)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_18px_60px_rgba(5,8,15,0.1)] sm:p-8" initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-100px" }} transition={{ duration: 0.5, delay: index * 0.1, ease: [0.4, 0, 0.2, 1] }} whileHover={{ y: -4, boxShadow: "var(--shadow-card-hover)", transition: { duration: 0.24, ease: [0.4, 0, 0.2, 1] } }}>
              <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-gold sm:text-[11px]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>{article.meta}</span>
              <h3 className="mt-2 text-[20px] font-semibold leading-[1.3] text-ink-primary sm:text-[22px] lg:text-[24px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>{article.title}</h3>
              <p className="mb-4 flex-grow text-[15px] leading-[1.55] text-ink-body">{article.excerpt}</p>
              <div className="flex items-center justify-between">
                <span className="font-mono text-[12px] text-ink-tertiary">{article.readingTime}</span>
                <motion.a href="#" className="flex items-center gap-1.5 text-[13px] font-medium text-gold" whileHover="hover">
                  <span>Read article</span>
                  <motion.span variants={{ hover: { x: 4 } }} transition={{ duration: 0.24, ease: [0.4, 0, 0.2, 1] }}><ArrowRight className="h-3 w-3" strokeWidth={1.5} /></motion.span>
                </motion.a>
              </div>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  );
}
