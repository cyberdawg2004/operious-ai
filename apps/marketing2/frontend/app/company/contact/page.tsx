import { ContactForm } from "@/components/contact-form";

type ContactPageProps = {
  searchParams?: Promise<{
    industry?: string;
    topic?: string;
    tier?: string;
  }>;
};

function normalizeDomain(industry?: string) {
  if (!industry) {
    return undefined;
  }

  const labels: Record<string, string> = {
    hardware: "Hardware",
    "financial-services": "Financial services",
    healthcare: "Healthcare",
    insurance: "Insurance",
    telecom: "Telecommunications",
    logistics: "Logistics",
    "public-sector": "Public sector",
  };

  return labels[industry];
}

export default async function ContactPage({ searchParams }: ContactPageProps) {
  const params = searchParams ? await searchParams : {};
  const context = params.topic ?? params.tier ?? params.industry;

  return (
    <main className="flex-1">
      <section className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16">
        <div className="mx-auto grid max-w-[1120px] gap-10 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <p
              className="text-[10px] uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              Company / Contact
            </p>
            <h1
              className="mt-5 text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              Book an architecture review.
            </h1>
            <p className="mt-6 text-[18px] leading-relaxed text-ink-secondary">
              Share the operational domain, ticket volume, and governance requirements
              you want Operious to review. The next step is an architecture conversation,
              not a generic product demo.
            </p>
            <div className="mt-8 rounded-md border border-border-subtle bg-white p-5">
              <p
                className="text-[10px] uppercase tracking-[0.18em] text-gold"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                Enterprise sales
              </p>
              <p className="mt-2 text-[15px] leading-relaxed text-ink-body">
                Reach out to our sales team using the secure form on this page.
                A solutions architect will respond within one business day to schedule
                the architecture review.
              </p>
            </div>
            {context && (
              <p
                className="mt-6 text-[11px] uppercase tracking-[0.18em] text-gold"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                Review context: {context}
              </p>
            )}
          </div>
          <ContactForm initialDomain={normalizeDomain(params.industry)} context={context} />
        </div>
      </section>
    </main>
  );
}
