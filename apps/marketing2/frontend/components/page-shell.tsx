import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Reveal, RevealGroup } from "@/components/reveal";
import type { PageContent, ContentCard } from "@/lib/page-content";
import type { SiteLink } from "@/lib/site-links";

function isExternal(href: string) {
  return href.startsWith("http") || href.startsWith("mailto:");
}

function CtaLink({ link }: { link: SiteLink }) {
  const className =
    "group inline-flex h-12 items-center justify-center rounded-md bg-ink-primary px-5 text-[14px] font-semibold text-white shadow-[0_10px_28px_rgba(10,15,28,0.18)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-ink-body hover:shadow-[0_16px_36px_rgba(10,15,28,0.26)]";

  if (isExternal(link.href)) {
    return (
      <a href={link.href} className={className}>
        {link.label}
        <ArrowRight className="ml-2 h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
      </a>
    );
  }

  return (
    <Link href={link.href} className={className}>
      {link.label}
      <ArrowRight className="ml-2 h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
    </Link>
  );
}

function ContentCardLink({ card }: { card: ContentCard }) {
  const content = (
    <article className="h-full rounded-md border border-border-subtle bg-white p-6 transition-all duration-300 hover:-translate-y-1 hover:border-gold hover:shadow-[var(--shadow-card-hover)]">
      {card.meta && (
        <p
          className="mb-3 text-[10px] uppercase tracking-[0.18em] text-gold"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          {card.meta}
        </p>
      )}
      <h3
        className="text-[22px] font-semibold leading-tight text-ink-primary"
        style={{ fontFamily: "var(--font-cormorant-sc)" }}
      >
        {card.title}
      </h3>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-body">{card.body}</p>
      {card.items && card.items.length > 0 && (
        <ul className="mt-4 space-y-2 text-[14px] leading-relaxed text-ink-body">
          {card.items.map((item) => (
            <li key={item} className="flex gap-2">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
      {card.href && (
        <span className="mt-5 inline-flex items-center text-[13px] font-medium text-gold">
          Open page
          <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
        </span>
      )}
    </article>
  );

  if (!card.href) {
    return content;
  }

  if (isExternal(card.href)) {
    return (
      <a href={card.href} className="block h-full">
        {content}
      </a>
    );
  }

  return (
    <Link href={card.href} className="block h-full">
      {content}
    </Link>
  );
}

export function PageShell({ content }: { content: PageContent }) {
  return (
    <main className="flex-1 overflow-x-hidden">
      <section className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16 lg:pb-24">
        <RevealGroup className="mx-auto max-w-[1120px]" mode="load">
          <Reveal>
            <p
              className="text-[10px] uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              {content.eyebrow}
            </p>
          </Reveal>
          <Reveal>
            <h1
              className="mt-5 max-w-[920px] text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              {content.title}
            </h1>
          </Reveal>
          <Reveal>
            <p className="mt-6 max-w-[820px] text-[18px] leading-relaxed text-ink-secondary sm:text-[20px]">
              {content.subtitle}
            </p>
          </Reveal>
          <Reveal>
            <div className="mt-10 grid gap-5 text-[16px] leading-relaxed text-ink-body md:grid-cols-2">
              {content.intro.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          </Reveal>
          {content.ctas && content.ctas.length > 0 && (
            <Reveal>
              <div className="mt-10 flex flex-col gap-3 sm:flex-row">
                {content.ctas.map((link) => (
                  <CtaLink key={`${link.label}-${link.href}`} link={link} />
                ))}
              </div>
            </Reveal>
          )}
        </RevealGroup>
      </section>

      {content.cards && content.cards.length > 0 && (
        <section className="bg-surface-raised px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
          <RevealGroup className="mx-auto grid max-w-[1120px] gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {content.cards.map((card) => (
              <Reveal key={`${card.title}-${card.href ?? "static"}`}>
                <ContentCardLink card={card} />
              </Reveal>
            ))}
          </RevealGroup>
        </section>
      )}

      <section className="bg-canvas px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto grid max-w-[1120px] gap-10 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <p
              className="text-[10px] uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              Operating detail
            </p>
            <h2
              className="mt-4 text-[34px] font-bold leading-tight text-ink-primary sm:text-[44px]"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              What this page establishes
            </h2>
          </div>
          <RevealGroup className="space-y-10">
            {content.sections.map((section) => (
              <Reveal key={section.title}>
                <section className="border-t border-border-subtle pt-6">
                  <h3
                    className="text-[26px] font-semibold text-ink-primary"
                    style={{ fontFamily: "var(--font-cormorant-sc)" }}
                  >
                    {section.title}
                  </h3>
                  <div className="mt-4 space-y-4 text-[16px] leading-relaxed text-ink-body">
                    {section.body.map((paragraph) => (
                      <p key={paragraph}>{paragraph}</p>
                    ))}
                    {section.bullets && section.bullets.length > 0 && (
                      <ul className="space-y-2">
                        {section.bullets.map((item) => (
                          <li key={item} className="flex gap-3">
                            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {section.code && (
                      <pre className="overflow-x-auto rounded-md border border-border-subtle bg-[#05080F] p-5 text-[13px] leading-relaxed text-[#D8E4F4]">
                        <code>{section.code}</code>
                      </pre>
                    )}
                  </div>
                </section>
              </Reveal>
            ))}
          </RevealGroup>
        </div>
      </section>
    </main>
  );
}
