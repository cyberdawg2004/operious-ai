'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { Button } from '@operious/ui';

const COMMAND_CENTER_URL =
  process.env.NEXT_PUBLIC_OPERIOUS_COMMAND_CENTER_URL ??
  'https://operious-ai-command-center.vercel.app';

export const PilotCtaSection = () => (
  <section id="pilot" className="border-b border-line bg-bg-subtle py-24">
    <div className="mx-auto max-w-3xl px-6 text-center">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: '-80px' }}
        transition={{ duration: 0.5 }}
        className="space-y-6"
      >
        <p className="font-mono text-2xs uppercase tracking-widest text-accent">
          Pilot Program
        </p>
        <h2 className="font-display text-3xl text-fg md:text-5xl">
          For enterprises who treat operations as infrastructure.
        </h2>
        <p className="text-base text-fg-muted md:text-lg">
          Pilots are accepted on alignment with the architectural law: deterministic
          runtime, governed memory evolution, explicit authority. We design Operious
          for organisations that already know an autonomous AI agent is not the answer.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
          <Button size="md" variant="primary" type="button">
            Request Pilot
          </Button>
          <Link href={COMMAND_CENTER_URL}>
            <Button size="md" variant="ghost" type="button">
              Inspect Command Center
            </Button>
          </Link>
        </div>
      </motion.div>
    </div>
  </section>
);
