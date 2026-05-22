'use client';

import { motion as fm, AnimatePresence } from 'framer-motion';
import { useState } from 'react';
import { Reveal } from '../ui/reveal';
import { SectionLabel } from '../ui/section-label';
import { easings, ms } from '@/lib/motion';

interface QA {
  readonly q: string;
  readonly a: string;
}

const FAQ: ReadonlyArray<QA> = [
  {
    q: 'How is this different from existing AI orchestration frameworks?',
    a: 'Frameworks like LangChain and AutoGen treat governance as a layer on top of execution. Operious treats governance as the substrate itself. Empty policy chains return deny, not allow. Substrate isolation is enforced at compile time. Constitutional violations break tests, not runtime.',
  },
  {
    q: 'Who owns the data and credentials in an Operious deployment?',
    a: 'The customer. All channel credentials, knowledge documents, and governance policies are stored encrypted per-tenant with isolated encryption keys. Operious infrastructure never co-mingles tenant data and never shares credentials across deployments.',
  },
  {
    q: 'How does Operious prevent the AI from exceeding policy?',
    a: 'The governance substrate evaluates every proposed action against deterministic policy chains before execution. A language model cannot override policy by phrasing output differently — the ToolInvoker only executes actions the governance substrate has approved. Policy denial is a mathematical boundary, not a request the model can negotiate.',
  },
  {
    q: 'What does forensic reconstruction mean in practice?',
    a: 'Every operational event is persisted with UUID5 cryptographic identity, parent lineage, governance provenance, and tenant authority. A complete decision can be replayed deterministically months or years later — proving exactly which policy applied, which knowledge informed the reasoning, and which authority approved the action.',
  },
  {
    q: 'How does Operious handle multilingual operations?',
    a: 'Multilingual input is translated to canonical English at the boundary, with a semantic preservation validator ensuring governance keywords do not drift during translation. The core reasoning substrate operates exclusively in canonical form. This isolates linguistic variance from operational logic.',
  },
  {
    q: 'What channels does Operious support?',
    a: 'Email, WhatsApp Business, Lark, Shulex, voice (via STT/TTS), and generic webhook ingress. Additional channel adapters are added on customer request. All channels normalize to a frozen boundary envelope before reaching the core.',
  },
  {
    q: 'Is there a self-service trial?',
    a: 'No. Operious deployments require tenant provisioning, policy configuration, and knowledge corpus onboarding — work that happens through structured enterprise engagement, not a sign-up form.',
  },
  {
    q: 'How quickly can an organization deploy Operious?',
    a: 'Initial deployment in two to four weeks. Full operational coverage of a specific workflow domain typically reaches steady state within sixty days of activation.',
  },
];

interface AccordionItemProps {
  readonly question: string;
  readonly answer: string;
  readonly open: boolean;
  readonly onToggle: () => void;
}

const AccordionItem = ({
  question,
  answer,
  open,
  onToggle,
}: AccordionItemProps) => (
  <div className="group py-6">
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      data-cursor="interactive"
      className="flex w-full cursor-pointer items-start justify-between gap-6 text-left"
    >
      <span className="heading-m text-ink-primary leading-snug">
        {question}
      </span>
      <span
        aria-hidden
        className={[
          'mt-1 flex h-6 w-6 flex-none items-center justify-center rounded-sm border border-line text-ink-secondary transition-transform duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]',
          open ? 'rotate-45' : '',
        ].join(' ')}
      >
        <svg width="10" height="10" viewBox="0 0 10 10">
          <path d="M5 1v8M1 5h8" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      </span>
    </button>
    <AnimatePresence initial={false}>
      {open ? (
        <fm.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: ms(320), ease: easings.precise }}
          style={{ overflow: 'hidden' }}
        >
          <p className="body-m text-ink-body mt-4 max-w-prose">{answer}</p>
        </fm.div>
      ) : null}
    </AnimatePresence>
  </div>
);

/**
 * SECTION 10 — FAQ  (light canvas, accordion)
 *
 * Animated height-to-auto expansion via Framer Motion. Hover causes the
 * gold thin line under each item to draw width 0% → 100% over 200ms.
 */
export const FaqSection = () => {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  return (
    <section
      id="faq"
      className="relative bg-canvas-raised border-y border-line-subtle"
    >
      <div className="mx-auto max-w-hero px-6 py-40 md:px-16">
        <Reveal>
          <SectionLabel index="08">QUESTIONS</SectionLabel>
        </Reveal>
        <Reveal delay={120}>
          <h2 className="heading-xl text-ink-primary mt-6 max-w-3xl">
            Frequently considered questions.
          </h2>
        </Reveal>

        <div className="mt-12 max-w-3xl">
          {FAQ.map((item, i) => (
            <Reveal key={item.q} delay={Math.min(i * 40, 320)}>
              <AccordionItem
                question={item.q}
                answer={item.a}
                open={openIndex === i}
                onToggle={() =>
                  setOpenIndex((cur) => (cur === i ? null : i))
                }
              />
              <div
                className="h-px origin-left scale-x-0 bg-gold/40 transition-transform duration-200 ease-[cubic-bezier(0.32,0.72,0,1)] group-[]:scale-x-100 hover:scale-x-100"
                aria-hidden
              />
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
};

export default FaqSection;
