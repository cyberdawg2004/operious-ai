import type { Metadata, Viewport } from 'next';
import { Cormorant_SC, IBM_Plex_Mono } from 'next/font/google';
import { GeistSans } from 'geist/font/sans';
import './globals.css';
import { SiteNav } from '@/components/nav/site-nav';
import { SiteFooter } from '@/components/site-footer';
import { FloatingChat } from '@/components/chat/floating-chat';
import { CustomCursor } from '@/components/atmospherics/custom-cursor';

/**
 * Typography stack (per Visual Execution Hyperprompt):
 *   • Display serif      : Cormorant SC (institutional, ≥ 28px only)
 *   • Body sans          : Geist Sans (replaces Inter — premium technical infra)
 *   • Technical mono     : IBM Plex Mono (tabular-nums enforced)
 *
 * Geist ships its own optimised loader. Cormorant SC and IBM Plex Mono are
 * loaded via next/font/google so they are subsetted, self-hosted, and
 * exposed as CSS variables (no CLS, swap fallback adjusted).
 */
const display = Cormorant_SC({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-display',
  weight: ['500', '600', '700'],
});

const mono = IBM_Plex_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-mono',
  weight: ['400', '500'],
});

export const metadata: Metadata = {
  metadataBase: new URL('https://operious.ai'),
  title: {
    default: 'Operious AI — Operational infrastructure that cannot deviate.',
    template: '%s · Operious AI',
  },
  description:
    'Operious AI is a deterministic execution substrate for enterprise operations. Mathematically enforced policy. Cryptographically reconstructible decisions. Replay-safe workflows that run identically, indefinitely, without drift.',
  applicationName: 'Operious AI',
  keywords: [
    'deterministic execution',
    'operational infrastructure',
    'governed AI',
    'fail-closed governance',
    'forensic decision lineage',
    'tenant isolation',
    'replay-safe',
    'enterprise operations',
  ],
  authors: [{ name: 'Operious AI' }],
  openGraph: {
    title: 'Operious AI — Operational infrastructure that cannot deviate.',
    description:
      'Deterministic execution substrate for enterprise operations. Mathematically enforced policy. Cryptographically reconstructible decisions.',
    type: 'website',
    locale: 'en_US',
    siteName: 'Operious AI',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Operious AI — Operational infrastructure that cannot deviate.',
    description:
      'Deterministic execution substrate for enterprise operations.',
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-snippet': -1,
      'max-image-preview': 'large',
      'max-video-preview': -1,
    },
  },
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
};

export const viewport: Viewport = {
  themeColor: '#F8F5EE',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${display.variable} ${mono.variable}`}
    >
      <body className="bg-canvas text-ink-body">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[80] focus:rounded-sm focus:bg-ink-primary focus:px-3 focus:py-2 focus:text-canvas-surface"
        >
          Skip to content
        </a>
        <CustomCursor />
        <SiteNav />
        <main id="main">{children}</main>
        <SiteFooter />
        <FloatingChat />
      </body>
    </html>
  );
}
