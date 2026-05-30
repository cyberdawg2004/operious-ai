import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Operious vs Platform AI Alternatives - Operious AI",
  description:
    "How Operious differs from AI features built into Zendesk, Salesforce, and ServiceNow.",
};

const alternatives = [
  {
    title: "Zendesk AI / Freshdesk",
    platform:
      "Platform AI: automates agent responses and ticket routing within the Zendesk environment.",
    operious:
      "Operious: governs which AI-initiated actions are authorized before they execute - in Zendesk, Salesforce, or any connected system. Policy, approval chains, and audit trail exist independent of platform.",
  },
  {
    title: "Salesforce Einstein",
    platform:
      "Platform AI: predicts and recommends inside the Salesforce data model.",
    operious:
      "Operious: enforces policy on any AI action that affects customer state, system records, or financial transactions - including those initiated inside Salesforce. The audit trail is platform-independent.",
  },
  {
    title: "ServiceNow AI",
    platform:
      "Platform AI: automates ITSM workflows within ServiceNow's process model.",
    operious:
      "Operious: adds a governed execution layer to operational workflows that span ServiceNow, your helpdesk, your CRM, and your back-office systems - with a single audit record covering the full workflow.",
  },
] as const;

export default function VsAlternativesPage() {
  return (
    <main className="flex-1 overflow-x-hidden">
      <section className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16 lg:pb-24">
        <div className="mx-auto max-w-[1120px]">
          <p
            className="text-[10px] uppercase tracking-[0.18em] text-gold"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            Platform / vs. Alternatives
          </p>
          <h1
            className="mt-5 max-w-[940px] text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            How Operious differs from AI tools built into your existing platforms
          </h1>
          <p className="mt-6 max-w-[820px] text-[18px] leading-relaxed text-ink-secondary sm:text-[20px]">
            Zendesk, Salesforce, and ServiceNow each offer AI capabilities inside
            their platforms. Operious is the governance layer that controls what
            those AI tools are permitted to do.
          </p>
        </div>
      </section>

      <section className="bg-surface-raised px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto grid max-w-[1280px] gap-5 lg:grid-cols-3">
          {alternatives.map((item) => (
            <article
              key={item.title}
              className="rounded-md border border-border-subtle bg-white p-6"
            >
              <h2
                className="text-[26px] font-semibold leading-tight text-ink-primary"
                style={{ fontFamily: "var(--font-cormorant-sc)" }}
              >
                {item.title}
              </h2>
              <p className="mt-5 text-[15px] leading-relaxed text-ink-body">
                {item.platform}
              </p>
              <p className="mt-5 border-t border-border-subtle pt-5 text-[15px] leading-relaxed text-ink-body">
                {item.operious}
              </p>
            </article>
          ))}
        </div>

        <div className="mx-auto mt-8 max-w-[1120px] rounded-md border border-border-subtle bg-white p-6">
          <p className="text-[17px] leading-relaxed text-ink-primary">
            Operious is not an alternative to your support or CRM platform. It is
            the governance infrastructure that makes AI actions in those platforms
            accountable.
          </p>
        </div>
      </section>
    </main>
  );
}
