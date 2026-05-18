'use client';

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import {
  DEFAULT_LOCALE,
  DICTIONARY,
  SUPPORTED_LOCALES,
  type Dictionary,
  type Locale,
} from './dictionary';

interface LocaleContextValue {
  readonly locale: Locale;
  readonly setLocale: (locale: Locale) => void;
  readonly t: Dictionary;
  readonly isRtl: boolean;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

interface LocaleProviderProps {
  readonly initialLocale?: Locale;
  readonly children: ReactNode;
}

export const LocaleProvider = ({
  initialLocale = DEFAULT_LOCALE,
  children,
}: LocaleProviderProps) => {
  const [locale, setLocale] = useState<Locale>(initialLocale);
  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      setLocale,
      t: DICTIONARY[locale],
      isRtl: locale === 'ar',
    }),
    [locale],
  );
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
};

export const useLocale = (): LocaleContextValue => {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error('useLocale called outside <LocaleProvider>');
  return ctx;
};

export { SUPPORTED_LOCALES };
