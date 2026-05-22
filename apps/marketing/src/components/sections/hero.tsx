'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { Button } from '@operious/ui';

const COMMAND_CENTER_URL =
  process.env.NEXT_PUBLIC_OPERIOUS_COMMAND_CENTER_URL ??
  'https://operious-ai-command-center.vercel.app';

export const HeroSection = () => (
  <section className="relative overflow-hidden border-b border-line">
    <div className="absolute inset-0 grid-bg opacity-60" aria-hidden />
    <div className="absolute inset-x-0 top-0 h-64 bg-gradient-to-b from-bg-raised/40 to-transparent" aria-hidden />
    <div className="relative mx-auto max-w-7xl px-6 py-32 md:py-48">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
        className="max-w-4xl space-y-8"
      >
        <p className="inline-flex items-center gap-2 rounded-sm border border-line-subtle bg-bg-inset px-2 py-1 font-mono text-2xs uppercase tracking-widest text-fg-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          Operious AI · Deterministic Operational Runtime
        </p>
        <h1 className="font-display text-4xl leading-[1.05] text-fg md:text-7xl">
          Governed organizational cognition,
          <br />
          <span className="text-fg-muted">engineered as infrastructure.</span>
        </h1>
        <p className="max-w-2xl text-lg text-fg-muted md:text-xl">
          Operious AI is not an autonomous-agent toy. It is the deterministic runtime
          your enterprise operations layer was missing — replay-safe, explicitly
          governed, end-to-end inspectable.
        </p>
        <div className="flex flex-wrap items-center gap-3 pt-4">
          <Link href="#pilot">
            <Button size="md" variant="primary">
              Request Pilot Access
            </Button>
          </Link>
          <Link href="#architecture">
            <Button size="md" variant="ghost">
              Read the Architecture
            </Button>
          </Link>
          <Link href={COMMAND_CENTER_URL}>
            <Button size="md" variant="subtle">
              Open Command Center
            </Button>
          </Link>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.8, delay: 0.4 }}
        className="mt-20 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line md:grid-cols-4"
      >
        {[
          { label: 'Runtime', value: 'Deterministic' },
          { label: 'Memory', value: 'Governed' },
          { label: 'Lineage', value: 'Replay-safe' },
          { label: 'Authority', value: 'Inspectable' },
        ].map((stat) => (
          <div key={stat.label} className="bg-bg-raised px-6 py-6">
            <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
              {stat.label}
            </p>
            <p className="mt-2 font-display text-2xl text-fg">{stat.value}</p>
          </div>
        ))}
      </motion.div>
    </div>
  </section>
);
