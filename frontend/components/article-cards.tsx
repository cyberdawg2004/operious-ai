"use client";

import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";

const articles = [
  {
    meta: "ENGINEERING · ARCHITECTURE",
    title: "Why Empty Policy Chains Must Return Deny.",
    excerpt:
      "The structural reason fail-closed governance is the only honest default for autonomous systems.",
    readingTime: "9 min read",
  },
  {
    meta: "DOCTRINE · OPERATIONS",
    title: "The Difference Between Throughput and Determinism.",
    excerpt:
      "Operations leaders are still optimizing the wrong variable.",
    readingTime: "12 min read",
  },
  {
    meta: "ENGINEERING · REPLAY",
    title: "Cryptographic Lineage Without Cryptographic Overhead.",
    excerpt:
      "How UUID5-based identity chains achieve tamper-evidence without the latency penalty of hash chaining.",
    readingTime: "7 min read",
  },
];

export function ArticleCards() {
  return (
    <section className="bg-canvas py-20 sm:py-28 lg:py-40 px-4 sm:px-8 lg:px-16">
      <div className="max-w-[1280px] mx-auto">
        {/* Section Header */}
        <div className="mb-12 sm:mb-16">
          <span
            className="font-mono text-[10px] sm:text-[11px] uppercase tracking-[0.18em] text-gold block mb-3 sm:mb-4"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            §07 · WRITING
          </span>
          <h2
            className="text-[36px] sm:text-[48px] lg:text-[64px] font-bold text-ink-primary leading-[1.1] mb-4 sm:mb-6"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Operational substrate thinking.
          </h2>
          <p className="font-sans text-[15px] sm:text-[16px] lg:text-[18px] text-ink-body leading-relaxed max-w-[760px]">
            Long-form editorial on governed AI execution, operational doctrine,
            and the engineering discipline behind deterministic infrastructure.
          </p>
        </div>

        {/* Article Cards Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 lg:gap-8">
          {articles.map((article, index) => (
            <motion.article
              key={index}
              className="bg-white border border-[var(--border-subtle)] rounded-lg p-6 sm:p-8 flex flex-col gap-3 cursor-pointer"
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-100px" }}
              transition={{
                duration: 0.5,
                delay: index * 0.1,
                ease: [0.4, 0, 0.2, 1],
              }}
              whileHover={{
                y: -4,
                boxShadow: "var(--shadow-card-hover)",
                transition: { duration: 0.24, ease: [0.4, 0, 0.2, 1] },
              }}
            >
              {/* Meta */}
              <span
                className="font-mono text-[10px] sm:text-[11px] uppercase tracking-[0.18em] text-gold"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                {article.meta}
              </span>

              {/* Title */}
              <h3
                className="text-[20px] sm:text-[22px] lg:text-[24px] font-semibold leading-[1.3] text-ink-primary mt-2"
                style={{ fontFamily: "var(--font-cormorant-sc)" }}
              >
                {article.title}
              </h3>

              {/* Excerpt */}
              <p className="font-sans text-[15px] leading-[1.55] text-ink-body flex-grow mb-4">
                {article.excerpt}
              </p>

              {/* Footer */}
              <div className="flex items-center justify-between">
                <span className="font-mono text-[12px] text-ink-tertiary">
                  {article.readingTime}
                </span>
                <motion.a
                  href="#"
                  className="flex items-center gap-1.5 font-sans text-[13px] font-medium text-gold group"
                  whileHover="hover"
                >
                  <span>Read article</span>
                  <motion.span
                    variants={{
                      hover: { x: 4 },
                    }}
                    transition={{ duration: 0.24, ease: [0.4, 0, 0.2, 1] }}
                  >
                    <ArrowRight className="w-3 h-3" strokeWidth={1.5} />
                  </motion.span>
                </motion.a>
              </div>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  );
}
