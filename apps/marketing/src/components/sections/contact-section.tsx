'use client';

import { useState } from 'react';
import { Reveal } from '../ui/reveal';

interface Track {
  readonly label: string;
  readonly heading: string;
  readonly body: string;
  readonly email: string;
}

const TRACKS: ReadonlyArray<Track> = [
  {
    label: 'GENERAL INQUIRIES',
    heading: 'Strategic context.',
    body: 'Strategic conversations, partnership exploration, and platform overview.',
    email: 'info@operious.com',
  },
  {
    label: 'ENTERPRISE OPERATIONS',
    heading: 'Deployment & onboarding.',
    body: 'Deployment planning, technical architecture, and customer operations onboarding.',
    email: 'ops@operious.com',
  },
  {
    label: 'CAREERS',
    heading: 'Engineering & field.',
    body: 'Engineering, operations, and field deployment opportunities.',
    email: 'career@operious.com',
  },
];

const INDUSTRIES = [
  'Hardware & Consumer Electronics',
  'Financial Services & Insurance',
  'Healthcare Operations',
  'Telecommunications',
  'Logistics & Supply Chain',
  'Public Sector Operations',
  'Other',
];

/**
 * SECTION 11 — CONTACT  (light canvas, narrow)
 *
 * Form fields stagger-reveal at 80ms intervals on section entry.
 * Submit button morphs to a checkmark + label on success.
 */
export const ContactSection = () => {
  const [submitted, setSubmitted] = useState(false);

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const subject = encodeURIComponent(
      `Operious enterprise inquiry — ${data.get('company') ?? ''}`,
    );
    const body = encodeURIComponent(
      [
        `Name: ${data.get('name')}`,
        `Company: ${data.get('company')}`,
        `Role: ${data.get('role')}`,
        `Industry: ${data.get('industry')}`,
        '',
        `${data.get('message')}`,
      ].join('\n'),
    );
    if (typeof window !== 'undefined') {
      window.location.href = `mailto:info@operious.com?subject=${subject}&body=${body}`;
    }
    setSubmitted(true);
  };

  return (
    <section id="contact" className="relative bg-canvas">
      <div className="mx-auto max-w-contact px-6 py-40">
        <Reveal>
          <p className="eyebrow text-gold">ENTERPRISE ENGAGEMENT</p>
        </Reveal>
        <Reveal delay={120}>
          <h2 className="heading-xl text-ink-primary mt-6">
            Begin the conversation.
          </h2>
        </Reveal>

        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {TRACKS.map((track, i) => (
            <Reveal
              key={track.label}
              delay={i * 80}
              className="rounded-md border border-line-subtle bg-canvas-surface p-6 transition-[transform,box-shadow] duration-[240ms] ease-[cubic-bezier(0.4,0,0.2,1)] hover:-translate-y-1 hover:shadow-card-hover"
            >
              <p className="eyebrow text-ink-tertiary">{track.label}</p>
              <p className="heading-m text-ink-primary mt-3">{track.heading}</p>
              <p className="body-s text-ink-body mt-3">{track.body}</p>
              <a
                href={`mailto:${track.email}`}
                data-cursor="interactive"
                className="mt-4 inline-block body-s text-gold hover:text-gold-highlight editorial-link"
              >
                {track.email}
              </a>
            </Reveal>
          ))}
        </div>

        <Reveal delay={240} className="mt-16">
          {submitted ? (
            <div className="rounded-md border border-gold/40 bg-canvas-surface px-6 py-6 text-center shadow-panel">
              <p className="eyebrow text-gold">CONVERSATION INITIATED</p>
              <p className="body-s text-ink-body mt-3">
                Your email client should now be open. If not, write to
                info@operious.com directly.
              </p>
            </div>
          ) : (
            <form
              onSubmit={onSubmit}
              className="space-y-5 rounded-md border border-line-subtle bg-canvas-surface p-8 shadow-panel"
            >
              <div className="grid gap-5 sm:grid-cols-2">
                <Field name="name" label="Name" required delay={0} />
                <Field name="company" label="Company" required delay={80} />
                <Field name="role" label="Role" delay={160} />
                <SelectField
                  name="industry"
                  label="Industry"
                  options={INDUSTRIES}
                  delay={240}
                />
              </div>
              <Reveal delay={320}>
                <TextArea name="message" label="Message" rows={4} />
              </Reveal>
              <Reveal delay={400}>
                <div className="flex justify-end">
                  <button
                    type="submit"
                    data-cursor="interactive"
                    className="rounded-sm bg-gold px-6 py-3 body-s text-dark-canvas transition-colors duration-[160ms] hover:bg-gold-deep"
                  >
                    Begin Conversation
                  </button>
                </div>
              </Reveal>
            </form>
          )}
        </Reveal>
      </div>
    </section>
  );
};

const Field = ({
  name,
  label,
  required,
  delay,
}: {
  readonly name: string;
  readonly label: string;
  readonly required?: boolean;
  readonly delay?: number;
}) => (
  <Reveal delay={delay ?? 0}>
    <label className="block">
      <span className="eyebrow text-ink-tertiary">
        {label}
        {required ? ' *' : ''}
      </span>
      <input
        name={name}
        required={required}
        data-cursor="text"
        className="mt-2 w-full rounded-sm border border-line bg-canvas-raised px-3 py-3 body-m text-ink-primary transition-[border-color] duration-200 focus:border-gold focus:outline-none"
      />
    </label>
  </Reveal>
);

const SelectField = ({
  name,
  label,
  options,
  delay,
}: {
  readonly name: string;
  readonly label: string;
  readonly options: ReadonlyArray<string>;
  readonly delay?: number;
}) => (
  <Reveal delay={delay ?? 0}>
    <label className="block">
      <span className="eyebrow text-ink-tertiary">{label}</span>
      <select
        name={name}
        defaultValue=""
        data-cursor="interactive"
        className="mt-2 w-full rounded-sm border border-line bg-canvas-raised px-3 py-3 body-m text-ink-primary transition-[border-color] duration-200 focus:border-gold focus:outline-none"
      >
        <option value="" disabled>
          Select an industry
        </option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </label>
  </Reveal>
);

const TextArea = ({
  name,
  label,
  rows,
}: {
  readonly name: string;
  readonly label: string;
  readonly rows: number;
}) => (
  <label className="block">
    <span className="eyebrow text-ink-tertiary">{label}</span>
    <textarea
      name={name}
      rows={rows}
      data-cursor="text"
      className="mt-2 w-full rounded-sm border border-line bg-canvas-raised px-3 py-3 body-m text-ink-primary transition-[border-color] duration-200 focus:border-gold focus:outline-none"
    />
  </label>
);

export default ContactSection;
