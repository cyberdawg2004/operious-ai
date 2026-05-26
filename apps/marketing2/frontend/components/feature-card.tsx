"use client";

import Link from "next/link";
import { ArrowRight, FileSearch, Network, Scale, ShieldCheck } from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";

const icons = {
  governance: Scale,
  replay: FileSearch,
  agents: Network,
  agi: ShieldCheck,
};

export function FeatureCard({
  title,
  body,
  href,
  iconName,
  index,
}: {
  title: string;
  body: string;
  href: string;
  iconName: keyof typeof icons;
  index: number;
}) {
  const reducedMotion = useReducedMotion();
  const Icon = icons[iconName];

  return (
    <motion.div
      initial={reducedMotion ? false : { opacity: 0, y: 28 }}
      whileInView={reducedMotion ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.28 }}
      transition={{ duration: 0.58, delay: index * 0.07, ease: [0.22, 1, 0.36, 1] }}
      whileHover={reducedMotion ? undefined : { y: -6 }}
      className="h-full"
    >
      <Link
        href={href}
        className="group relative block h-full overflow-hidden rounded-md border border-border-subtle bg-white p-7 shadow-[var(--shadow-card)] transition-colors duration-300 hover:border-gold"
      >
        <span className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#C9A84C]/80 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
        <span className="absolute inset-0 bg-[linear-gradient(135deg,rgba(42,92,170,0.06),transparent_42%)] opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
        <span className="relative flex h-11 w-11 items-center justify-center border border-[#E5DCC8] bg-[#FBF9F4]">
          <Icon className="h-5 w-5 text-gold" />
        </span>
        <h3
          className="relative mt-6 text-[24px] font-semibold leading-tight text-ink-primary"
          style={{ fontFamily: "var(--font-cormorant-sc)" }}
        >
          {title}
        </h3>
        <p className="relative mt-3 text-[15px] leading-relaxed text-ink-body">{body}</p>
        <span className="relative mt-6 inline-flex items-center text-[13px] font-medium text-gold">
          Open pillar
          <ArrowRight className="ml-1.5 h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
        </span>
      </Link>
    </motion.div>
  );
}
