import Link from "next/link";
import { ArrowRight } from "lucide-react";

type Concern = {
  label: string;
  body: string;
  href?: string;
};

type SolutionPageProps = {
  eyebrow: string;
  title: string;
  intro?: string;
  concerns: Concern[];
  ctaLabel: string;
  ctaHref: string;
};

export function SolutionPage({
  eyebrow,
  title,
  intro,
  concerns,
  ctaLabel,
  ctaHref,
}: SolutionPageProps) {
  return (
    <main className="flex-1 overflow-x-hidden">
      <section className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16 lg:pb-24">
        <div className="mx-auto max-w-[1120px]">
          <p
            className="text-[10px] uppercase tracking-[0.18em] text-gold"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {eyebrow}
          </p>
          <h1
            className="mt-5 max-w-[940px] text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            {title}
          </h1>
          {intro && (
            <p className="mt-6 max-w-[760px] text-[18px] leading-relaxed text-ink-secondary sm:text-[20px]">
              {intro}
            </p>
          )}
        </div>
      </section>

      <section className="bg-surface-raised px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto grid max-w-[1120px] gap-5 lg:grid-cols-3">
          {concerns.map((concern) => (
            <article
              key={concern.label}
              className="rounded-md border border-border-subtle bg-white p-6"
            >
              <p
                className="text-[10px] uppercase tracking-[0.18em] text-gold"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                {concern.label}
              </p>
              <p className="mt-5 text-[16px] leading-relaxed text-ink-body">
                {concern.body}
              </p>
              {concern.href && (
                <Link
                  href={concern.href}
                  className="mt-5 inline-flex items-center text-[13px] font-medium text-gold"
                >
                  Open reference
                  <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
                </Link>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="bg-canvas px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto max-w-[1120px]">
          <Link
            href={ctaHref}
            className="inline-flex h-12 items-center justify-center rounded-md bg-ink-primary px-5 text-[14px] font-semibold text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-ink-body"
          >
            {ctaLabel}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </section>
    </main>
  );
}
