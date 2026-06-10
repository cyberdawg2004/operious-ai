import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

export const metadata: Metadata = {
  title: "Why Multilingual BPO Operations Fail at Scale - Operious AI",
  description:
    "An Operious article on Arabic language gaps, multilingual governance, and audit completeness in enterprise operations.",
};

const failureModes = [
  "Language detection accuracy at the routing layer.",
  "Governance consistency across languages.",
  "Audit trail completeness for non-English interactions.",
  "Policy enforcement that works regardless of language.",
];

const requirements = [
  "Detection at ingress, not only after a ticket is routed.",
  "Translation to a canonical processing language.",
  "Policy evaluation on normalized content.",
  "Response translation back to the customer's language.",
  "Audit trail coverage across every step in the language path.",
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

export default function MultilingualEnterpriseOperationsArticle() {
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
            Why multilingual BPO operations fail at scale
          </h1>

          <div className="mt-10 space-y-6 text-[17px] leading-relaxed text-ink-body">
            <p>
              The Arabic language gap is one of the clearest signals that global
              support operations were not designed for governed automation. Most
              enterprise support operations treat non-English as a secondary concern
              handled by specialist teams, outsourced BPOs, or routing rules that
              move the message away from the main operating queue. For global
              consumer electronics, telco, insurance, and healthcare companies,
              this creates a two-tier support experience. English-language contacts
              receive faster automation and richer analytics. Arabic-language
              contacts are more likely to wait, escalate, or disappear into queues
              with thinner measurement.
            </p>
            <p>
              That gap damages NPS, but it also increases operational risk. A warranty
              claim, refund request, billing dispute, device defect, or policy exception
              does not become less important because the customer wrote in Arabic,
              Indonesian, or mixed English. The decision still needs a policy path,
              a confidence threshold, an escalation rule, and an audit record that
              can explain what happened later.
            </p>
          </div>

          <section className="mt-12 border-t border-border-subtle pt-8">
            <h2
              className="text-[34px] font-semibold leading-tight text-ink-primary"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              The failure modes
            </h2>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The first failure mode is language detection at the routing layer.
              Many operations stacks detect language only to choose a queue or macro.
              That is too late for governed execution. Language must be part of
              the ingress evidence because it affects classification, translation,
              policy selection, and supervisor review. If the system guesses wrong
              at ingress, every later step inherits that error.
            </p>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The second failure mode is governance inconsistency across languages.
              Enterprises often maintain English policy documents, then rely on
              agents or translation layers to apply them elsewhere. That creates
              uneven enforcement. A refund threshold, replacement authorization,
              sensitive complaint rule, or escalation condition should not vary
              because the source text was Arabic rather than English.
            </p>
            <ArticleList items={failureModes} />
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The third failure mode is audit trail incompleteness. A platform may
              log the final translated answer while losing the original message,
              language confidence, translation artifact, normalized content, and
              policy decision. When a customer challenges the outcome, the company
              cannot reconstruct the language path. It can only show the last text
              emitted by the system.
            </p>
          </section>

          <section className="mt-12 border-t border-border-subtle pt-8">
            <h2
              className="text-[34px] font-semibold leading-tight text-ink-primary"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              What governed multilingual operations require
            </h2>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              Governed multilingual operations start before routing. The system
              detects language at ingress, records confidence, and preserves the
              original text. It then translates to a canonical processing language
              so classification, policy retrieval, and governance evaluation happen
              against a normalized representation. That does not mean the source
              language disappears. It remains part of the evidence bundle.
            </p>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The response path must also be governed. A reply translated back to
              the customer&apos;s language is still an operational action. It may contain
              a promise, a denial, a replacement instruction, or a refund explanation.
              The policy decision that allows the response should be tied to the
              original source text, the canonical content, the retrieved procedure,
              and the localized output.
            </p>
            <ArticleList items={requirements} />
          </section>

          <section className="mt-12 border-t border-border-subtle pt-8">
            <h2
              className="text-[34px] font-semibold leading-tight text-ink-primary"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              What Operious does
            </h2>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              Operious treats language as operational evidence, not a cosmetic
              localization layer. The RT9 implementation uses langdetect with a
              deterministic seed for repeatable language detection. Messages move
              through a translation pipeline into canonical content, governance is
              evaluated on that normalized content, and localization happens again
              at egress. Six languages can share one governance standard because
              the policy layer evaluates the operational subject rather than the
              surface language alone.
            </p>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The audit trail covers each step: original message, detected language,
              confidence, translation artifact, canonical classification, policy
              decision, generated response, and localized response. Supervisors can
              review where confidence was low, why escalation occurred, and which
              policy version governed the action. That is the difference between
              translated support and governed multilingual operations.
            </p>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-body">
              The Arabic gap is not a niche problem for APAC companies. It is a
              structural failure in how enterprise operations are designed for
              language. Operious resolves it at the infrastructure layer: detection,
              normalization, governance, localization, and audit under one operating
              standard.
            </p>
          </section>

          <Link
            href="/company/contact?topic=Multilingual%20Operations%20Review"
            className="mt-12 inline-flex h-12 items-center justify-center rounded-md bg-ink-primary px-5 text-[14px] font-semibold text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-ink-body"
          >
            Book a language operations review
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </article>
    </main>
  );
}
