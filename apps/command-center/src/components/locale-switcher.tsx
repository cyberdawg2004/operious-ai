'use client';

import { useLocale, SUPPORTED_LOCALES } from '@/locale/provider';
import type { Locale } from '@/locale/dictionary';

const LABELS: Record<Locale, string> = {
  en: 'EN',
  es: 'ES',
  ar: 'AR',
};

export const LocaleSwitcher = () => {
  const { locale, setLocale } = useLocale();
  return (
    <div
      className="inline-flex items-center gap-1 rounded-sm border border-line bg-bg-inset p-0.5"
      role="radiogroup"
      aria-label="Locale"
    >
      {SUPPORTED_LOCALES.map((entry) => {
        const active = entry === locale;
        return (
          <button
            key={entry}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setLocale(entry)}
            className={`px-2 py-1 font-mono text-2xs uppercase tracking-wider rounded-sm ${
              active
                ? 'bg-bg-raised text-fg border border-line-strong'
                : 'text-fg-subtle hover:text-fg'
            }`}
          >
            {LABELS[entry]}
          </button>
        );
      })}
    </div>
  );
};
