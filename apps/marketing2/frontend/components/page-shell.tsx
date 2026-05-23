import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { PageContent, ContentCard } from "@/lib/page-content";
import type { SiteLink } from "@/lib/site-links";

function isExternal(href: string) {
  return href.startsWith("http") || href.startsWith("mailto:");
}

function CtaLink({ link }: { link: SiteLink }) {
  const className =
    "inline-flex h-12 items-center justify-center rounded-md bg-ink-primary px-5 text-[14px] font-semibold text-white transition-colors hover:bg-ink-body";

  if (isExternal(link.href)) {
    return (
      <a href={link.href} className={className}>
        {link.label}
        <ArrowRight className="ml-2 h-4 w-4" />
      </a>
    );
  }

  return (
    <Link href={link.href} className={className}>
      {link.label}
      <ArrowRight className="ml-2 h-4 w-4" />
    </Link>
  );
}

function ContentCardLink({ card }: { card: ContentCard }) {
  const content = (
    <article className="h-full rounded-md border border-border-subtle bg-white p-6 transition-shadow hover:shadow-[var(--shadow-card-hover)]">
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
    <main className="flex-1">
      <section className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16 lg:pb-24">
        <div className="mx-auto max-w-[1120px]">
          <p
            className="text-[10px] uppercase tracking-[0.18em] text-gold"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {content.eyebrow}
          </p>
          <h1
            className="mt-5 max-w-[920px] text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            {content.title}
          </h1>
          <p className="mt-6 max-w-[820px] text-[18px] leading-relaxed text-ink-secondary sm:text-[20px]">
            {content.subtitle}
          </p>
          <div className="mt-10 grid gap-5 text-[16px] leading-relaxed text-ink-body md:grid-cols-2">
            {content.intro.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </div>
          {content.ctas && content.ctas.length > 0 && (
            <div className="mt-10 flex flex-col gap-3 sm:flex-row">
              {content.ctas.map((link) => (
                <CtaLink key={`${link.label}-${link.href}`} link={link} />
              ))}
            </div>
          )}
        </div>
      </section>

      {content.cards && content.cards.length > 0 && (
        <section className="bg-surface-raised px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
          <div className="mx-auto grid max-w-[1120px] gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {content.cards.map((card) => (
              <ContentCardLink key={`${card.title}-${card.href ?? "static"}`} card={card} />
            ))}
          </div>
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
          <div className="space-y-10">
            {content.sections.map((section) => (
              <section key={section.title} className="border-t border-border-subtle pt-6">
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
                </div>
              </section>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
