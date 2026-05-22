import Link from 'next/link';
import { Reveal } from '../ui/reveal';
import { SectionLabel } from '../ui/section-label';

interface Article {
  readonly date: string;
  readonly category: string;
  readonly title: string;
  readonly excerpt: string;
  readonly readingTime: string;
}

const ARTICLES: ReadonlyArray<Article> = [
  {
    date: 'May 2026',
    category: 'Engineering · Architecture',
    title: 'Why Empty Policy Chains Must Return Deny.',
    excerpt:
      'The structural reason fail-closed governance is the only honest default for autonomous systems.',
    readingTime: '9 min read',
  },
  {
    date: 'May 2026',
    category: 'Doctrine · Operations',
    title: 'The Difference Between Throughput and Determinism.',
    excerpt:
      'Operations leaders are still optimizing the wrong variable.',
    readingTime: '12 min read',
  },
  {
    date: 'April 2026',
    category: 'Engineering · Replay',
    title: 'Cryptographic Lineage Without Cryptographic Overhead.',
    excerpt:
      'How UUID5 identity replaces hash chains in operational event fabrics.',
    readingTime: '7 min read',
  },
];

/**
 * SECTION 8 — EDITORIAL  (light canvas)
 *
 * Three featured article cards. Date strip reveals first inside each card
 * (stagger 80ms within card), then title, then excerpt — the editorial
 * "byline → headline → lede" rhythm.
 */
export const EditorialSection = () => (
  <section id="editorial" className="relative grain-light bg-canvas">
    <div className="mx-auto max-w-hero px-6 py-40 md:px-16">
      <Reveal>
        <SectionLabel index="07">WRITING</SectionLabel>
      </Reveal>
      <Reveal delay={120} className="mt-6 max-w-3xl">
        <h2 className="heading-xl text-ink-primary">
          Operational substrate thinking.
        </h2>
        <p className="body-l text-ink-body mt-6">
          Long-form editorial on governed AI execution, operational doctrine,
          and the engineering discipline behind deterministic infrastructure.
        </p>
      </Reveal>

      <div className="mt-16 grid gap-8 md:grid-cols-3">
        {ARTICLES.map((article, i) => (
          <Reveal
            key={article.title}
            delay={i * 80}
            className="group flex h-full flex-col rounded-md border border-line-subtle bg-canvas-surface p-6 transition-[transform,box-shadow] duration-[240ms] ease-[cubic-bezier(0.4,0,0.2,1)] hover:-translate-y-1 hover:shadow-card-hover"
          >
            <div className="flex items-center gap-3 eyebrow text-ink-tertiary">
              <span>{article.date}</span>
              <span aria-hidden>·</span>
              <span>{article.category}</span>
            </div>
            <h3 className="heading-m text-ink-primary mt-4 leading-snug">
              {article.title}
            </h3>
            <p className="body-s text-ink-body mt-4">{article.excerpt}</p>
            <div className="mt-auto pt-6 flex items-center justify-between">
              <span className="eyebrow text-ink-tertiary">
                {article.readingTime}
              </span>
              <span className="inline-flex items-center gap-1 body-s text-gold transition-colors group-hover:text-gold-highlight">
                <span className="editorial-link">Read</span>
                <span
                  aria-hidden
                  className="transition-transform duration-200 group-hover:translate-x-1"
                >
                  →
                </span>
              </span>
            </div>
          </Reveal>
        ))}
      </div>

      <Reveal delay={300} className="mt-12">
        <Link
          href="#editorial"
          data-cursor="interactive"
          className="inline-flex items-center gap-2 body-s text-gold hover:text-gold-highlight"
        >
          <span className="editorial-link">View all articles</span>
          <span aria-hidden>→</span>
        </Link>
      </Reveal>
    </div>
  </section>
);

export default EditorialSection;
