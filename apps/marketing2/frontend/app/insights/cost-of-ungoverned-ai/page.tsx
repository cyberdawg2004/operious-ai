import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

export const metadata: Metadata = {
  title: "The Operational and Legal Cost of Ungoverned AI - Operious AI",
  description:
    "An Operious article on regulatory, financial, reputational, and compliance risk from ungoverned AI execution.",
};

const riskItems = [
  "Regulatory exposure when AI decisions cannot be proven.",
  "Financial leakage from unverified refund and warranty execution.",
  "Reputational risk from inconsistent AI behavior at scale.",
  "Compliance failure when audit evidence does not exist.",
];

const currentControls = [
  "Human review of a fraction of AI decisions.",
  "Post-hoc logging that does not capture the decision chain.",
  "Policy documents that AI models read but cannot enforce.",
];

function ArticleList({ items }: { items: string[] }) {
  return (
    <ul className="mt-5 space-y-3">
      {items.map((item) => (
        <li key={item} className="flex gap-3 text-[16px] leading-relaxed text-ink-body">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export default function CostOfUngovernedAiArticle() {
  return (
    <main className="flex-1 overflow-x-hidden">
      <article className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16 lg:pb-24">
        <div className="mx-auto max-w-[860px]">
          <p
            className="text-[10px] uppercase tracking-[0.18em] text-gold"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            Insights
          </p>
          <h1
            className="mt-5 text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            The operational and legal cost of ungoverned AI execution in enterprise operations
          </h1>

          <div className="mt-10 space-y-6 text-[17px] leading-relaxed text-ink-body">
            <p>
              Every AI agent in enterprise operations is making decisions that have
              legal, financial, or reputational consequences. Warranty approvals.
              Refund authorizations. Escalation routing. Policy exceptions. Customer
              communications. Each action may look small in isolation, but at
              enterprise volume these decisions become a control system for the
              business. If that control system cannot prove why it acted, the company
              inherits risk faster than it gains efficiency.
            </p>
            <p>
              The central risk is not that a model writes imperfect language. The
              central risk is ungoverned execution: an AI system changes customer
              state, commits money, routes sensitive cases, denies service, or issues
              a response without a durable authorization record. That creates a gap
              between what the enterprise says its policy is and what its automation
              actually did.
            </p>
          </div>

          <section className="mt-12 border-t border-border-subtle pt-8">
            <h2
              className="text-[34px] font-semibold leading-tight text-ink-primary"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              The quantified risk
            </h2>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              Regulatory exposure appears when an organization cannot prove the
              chain behind a decision. A support automation may deny a warranty
              claim, classify a fraud-adjacent case, or trigger a customer-facing
              message. If the enterprise cannot show the evidence, policy version,
              confidence threshold, and reviewer path, the decision becomes difficult
              to defend under audit or dispute.
            </p>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              Financial leakage is equally concrete. Refunds, replacements, credits,
              goodwill concessions, and warranty approvals all move value. If an AI
              agent can approve or recommend those actions without a policy gate,
              the organization may discover leakage only after the money is gone.
              The reverse failure is also expensive: legitimate cases denied or
              delayed because the automation lacked a governed path to approve them.
            </p>
            <ArticleList items={riskItems} />
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              Reputational risk follows inconsistency. Customers compare outcomes.
              Regulators and journalists ask why similar cases received different
              treatment. Internal teams ask why the model was permitted to act at
              all. Without governance, the company is left explaining behavior it
              cannot reconstruct.
            </p>
          </section>

          <section className="mt-12 border-t border-border-subtle pt-8">
            <h2
              className="text-[34px] font-semibold leading-tight text-ink-primary"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              What companies currently do about this
            </h2>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The most common mitigation is partial human review. Teams sample a
              subset of AI decisions, inspect escalations, or ask supervisors to
              review sensitive categories. Sampling is useful for quality, but it
              is not an execution control. It finds some failures after the fact.
              It does not prevent unauthorized actions before they occur.
            </p>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              Another mitigation is post-hoc logging. Logs can show that a service
              called another service, but they often fail to capture the decision
              chain: what evidence was used, which policy version applied, whether
              threshold conditions passed, who approved the exception, and what
              alternative paths were denied. Logs are useful for engineering
              diagnosis. They are weak as the primary source of operational evidence.
            </p>
            <ArticleList items={currentControls} />
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The third mitigation is policy-as-prompt. A team writes policy guidance
              into system prompts or knowledge documents and asks the model to follow
              it. That may improve behavior, but it does not enforce authority. The
              model can misunderstand, omit, or contradict policy. More importantly,
              a prompt does not create a persisted authorization decision before an
              action executes.
            </p>
          </section>

          <section className="mt-12 border-t border-border-subtle pt-8">
            <h2
              className="text-[34px] font-semibold leading-tight text-ink-primary"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              The architectural answer
            </h2>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The governance layer is not a policy document or a prompt. It is
              infrastructure that runs before every action executes. A proposed
              action should carry an actor, tenant, capability, subject, evidence
              bundle, confidence score, and policy version. The governance runtime
              evaluates that proposal, returns ALLOW, DENY, or review, and records
              the result before execution can mutate a system or contact a customer.
            </p>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              Operious is designed around that model. Governance fails closed. Empty
              policy chains deny. Missing evidence denies. Decisions are append-only
              and cryptographically signed with HMAC-SHA256. Session and decision
              identities use deterministic UUID5 where stable identity can be derived.
              The audit record is not reconstructed later from loose logs. It is
              produced by the execution path itself.
            </p>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The companies that build governance infrastructure now will not be
              explaining ungoverned AI decisions later. The cost of building it after
              a regulatory event is orders of magnitude higher than the cost of
              building it before. Governance is the price of making automation durable
              enough for real enterprise operations.
            </p>
          </section>

          <Link
            href="/company/contact?topic=Governed%20AI%20Architecture%20Review"
            className="mt-12 inline-flex h-12 items-center justify-center rounded-md bg-ink-primary px-5 text-[14px] font-semibold text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-ink-body"
          >
            Book a governance architecture review
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </article>
    </main>
  );
}
