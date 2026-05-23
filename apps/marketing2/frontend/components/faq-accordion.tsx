"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Plus } from "lucide-react";

const faqItems = [
  {
    question: "How is this different from existing AI orchestration frameworks?",
    answer:
      "Frameworks like LangChain and AutoGen treat governance as a layer on top of execution. Operious treats governance as the substrate itself. Empty policy chains return deny, not allow. Substrate isolation is enforced at compile time. Constitutional violations break tests, not runtime.",
  },
  {
    question: "Who owns the data and credentials in an Operious deployment?",
    answer:
      "The customer. All channel credentials, knowledge documents, and governance policies are stored encrypted per-tenant with isolated encryption keys. Operious infrastructure never co-mingles tenant data and never shares credentials across deployments.",
  },
  {
    question: "How does Operious prevent the AI from exceeding policy?",
    answer:
      "The governance substrate evaluates every proposed action against deterministic policy chains before execution. A language model cannot invoke a tool, send a message, or modify state without an explicit policy permit. The permit is logged immutably. If no permit exists, the action is denied by default.",
  },
  {
    question: "What happens when the language model hallucinates?",
    answer:
      "Hallucination is an output problem, not an execution problem. Operious separates generation from action. The model may generate incorrect text, but that text cannot become an action without passing through the governance substrate. Governance policy can require human approval, secondary verification, or deterministic validation before any proposed action executes.",
  },
  {
    question: "Can Operious integrate with our existing enterprise systems?",
    answer:
      "Yes. Operious provides typed channel adapters for common enterprise systems including Salesforce, ServiceNow, Workday, SAP, and custom REST/GraphQL APIs. Each adapter enforces the same governance substrate—credentials are isolated, actions are permitted, and all interactions are logged to the immutable audit trail.",
  },
  {
    question: "How do we audit what the AI did and why?",
    answer:
      "Every execution produces a cryptographically signed trace containing the full decision path: input received, policy evaluated, permits granted, tools invoked, outputs generated. Traces are immutable and exportable. Compliance teams can replay any decision to understand exactly what happened and why.",
  },
];

export function FaqAccordion() {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const handleToggle = (index: number) => {
    setOpenIndex(openIndex === index ? null : index);
  };

  return (
    <section className="bg-canvas py-20 sm:py-28 lg:py-40 px-4 sm:px-8 lg:px-16">
      <div className="mx-auto max-w-[880px]">
        {/* Section Title */}
        <h2
          className="text-[36px] sm:text-[48px] lg:text-[64px] font-bold leading-[1.1] tracking-[-0.02em] text-ink-primary mb-10 sm:mb-12 lg:mb-16"
          style={{ fontFamily: "var(--font-cormorant-sc)" }}
        >
          Frequently considered questions.
        </h2>

        {/* Accordion List */}
        <div className="flex flex-col">
          {faqItems.map((item, index) => (
            <AccordionItem
              key={index}
              question={item.question}
              answer={item.answer}
              isOpen={openIndex === index}
              onToggle={() => handleToggle(index)}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

interface AccordionItemProps {
  question: string;
  answer: string;
  isOpen: boolean;
  onToggle: () => void;
}

function AccordionItem({ question, answer, isOpen, onToggle }: AccordionItemProps) {
  return (
    <div className="border-b border-gold">
      <motion.button
        onClick={onToggle}
        className="w-full py-6 flex items-start justify-between text-left transition-colors duration-100"
        whileHover={{ backgroundColor: "rgba(168, 136, 44, 0.04)" }}
      >
        <span
          className="text-[18px] sm:text-[20px] lg:text-[22px] font-semibold leading-[1.4] text-ink-primary pr-6 sm:pr-8"
          style={{ fontFamily: "var(--font-cormorant-sc)" }}
        >
          {question}
        </span>
        <motion.div
          animate={{ rotate: isOpen ? 45 : 0 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          className="flex-shrink-0 mt-1"
        >
          <Plus className="w-5 h-5 text-ink-tertiary" strokeWidth={1.5} />
        </motion.div>
      </motion.button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{
              duration: 0.32,
              ease: "easeOut",
            }}
            className="overflow-hidden"
          >
            <p className="pb-6 pt-2 sm:pt-4 text-[14px] sm:text-[15px] lg:text-[16px] leading-[1.6] text-ink-body font-sans">
              {answer}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
