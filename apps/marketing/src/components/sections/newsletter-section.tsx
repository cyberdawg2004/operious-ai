'use client';

import { useState } from 'react';
import { Reveal } from '../ui/reveal';

/**
 * SECTION 9 — NEWSLETTER  (light canvas, narrow)
 *
 * Centered, max-width 680px. On submit the button morphs to a checkmark
 * + "Subscribed" state (per spec: 400ms morph). The focused input draws
 * a gold underline left-to-right (handled via CSS hairline-draw).
 */
export const NewsletterSection = () => {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email.includes('@')) return;
    setSubmitted(true);
  };

  return (
    <section id="newsletter" className="relative bg-canvas">
      <div className="mx-auto max-w-narrow px-6 py-40 text-center">
        <Reveal>
          <p className="eyebrow text-gold">
            THE OPERATIONAL SUBSTRATE BRIEF
          </p>
        </Reveal>
        <Reveal delay={120}>
          <h2 className="heading-xl text-ink-primary mt-6">
            Weekly intelligence on governed execution.
          </h2>
        </Reveal>
        <Reveal delay={240}>
          <p className="body-l text-ink-body mt-5">
            A short, edited brief delivered to operations executives,
            compliance officers, and infrastructure architects. No
            promotions. No newsletters about newsletters.
          </p>
        </Reveal>

        <Reveal delay={360}>
          {submitted ? (
            <div className="mt-10 inline-flex items-center gap-3 rounded-sm border border-gold/40 bg-canvas-surface px-6 py-5 shadow-panel">
              <span
                aria-hidden
                className="flex h-6 w-6 items-center justify-center rounded-full bg-gold text-canvas-surface"
              >
                <svg width="12" height="12" viewBox="0 0 12 12">
                  <path
                    d="M2.5 6.5l2.5 2.5 4.5-5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <div className="text-left">
                <p className="eyebrow text-gold">SUBSCRIBED</p>
                <p className="body-s text-ink-body mt-1">
                  The next brief will arrive on the following Tuesday at
                  06:00 UTC.
                </p>
              </div>
            </div>
          ) : (
            <form
              onSubmit={onSubmit}
              className="mt-10 flex flex-col gap-3 sm:flex-row"
            >
              <label htmlFor="newsletter-email" className="sr-only">
                Email address
              </label>
              <input
                id="newsletter-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@yourorg.com"
                data-cursor="text"
                className="flex-1 rounded-sm border border-line bg-canvas-surface px-4 py-3 body-m text-ink-primary placeholder:text-ink-tertiary transition-[border-color] duration-200 focus:border-gold focus:outline-none"
              />
              <button
                type="submit"
                data-cursor="interactive"
                className="rounded-sm bg-gold px-6 py-3 body-s text-dark-canvas transition-colors duration-[160ms] hover:bg-gold-deep"
              >
                Subscribe
              </button>
            </form>
          )}
        </Reveal>

        <Reveal delay={480}>
          <p className="caption text-ink-tertiary mt-6">
            Read by operators at hardware, financial, and healthcare
            organizations. Unsubscribe anytime.
          </p>
        </Reveal>
      </div>
    </section>
  );
};

export default NewsletterSection;
