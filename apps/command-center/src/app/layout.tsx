import type { Metadata } from 'next';
import { IBM_Plex_Mono, Cormorant_SC } from 'next/font/google';
import { GeistSans } from 'geist/font/sans';
import './globals.css';
import { Providers } from './providers';
import { Sidebar } from '@/components/layout/sidebar';
import { NotificationStrip } from '@/components/layout/notification-strip';

/**
 * Typography stack (per Visual Execution Hyperprompt):
 *   • Display serif : Cormorant SC  (≥ 28px floor — institutional only)
 *   • Body sans     : Geist Sans   (Inter has been removed)
 *   • Technical mono: IBM Plex Mono (tabular-nums enforced)
 *
 * The Command Center stays restrained in chrome and lets the forensic
 * surfaces (Trace Inspector, Operations Queue) carry the alive feeling.
 */
const plexMono = IBM_Plex_Mono({
  weight: ['400', '500'],
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-plex-mono',
});

const cormorant = Cormorant_SC({
  weight: ['400', '500', '700'],
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-cormorant',
});

export const metadata: Metadata = {
  title: 'Operious Command Center',
  description:
    'Operational cognition dashboard for enterprise governance and oversight.',
};

/**
 * Root layout.
 *
 * Three-region: sidebar (240px) │ center (flex) │ right panel (480px,
 * mounted globally inside <RightPanelProvider>, slides in on demand).
 */
export default function CommandCenterLayout({
  children,
}: {
  readonly children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${plexMono.variable} ${cormorant.variable}`}
    >
      <body className="bg-bg text-fg antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex min-h-screen flex-1 flex-col">
              <NotificationStrip />
              <main className="flex-1 overflow-y-auto px-12 py-8">
                {children}
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
