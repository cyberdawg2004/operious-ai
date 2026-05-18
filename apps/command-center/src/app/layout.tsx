import type { Metadata } from 'next';
import './globals.css';
import { Providers } from './providers';
import { Sidebar } from '@/components/sidebar';
import { Topbar } from '@/components/topbar';

export const metadata: Metadata = {
  title: 'Operious Command Center',
  description: 'Operational cognition dashboard. Read-only inspection.',
};

export default function CommandCenterLayout({
  children,
}: {
  readonly children: React.ReactNode;
}) {
  return (
    <html lang="en" className="bg-bg">
      <body className="bg-bg text-fg antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex min-h-screen flex-1 flex-col">
              <Topbar />
              <div className="flex-1 overflow-y-auto px-8 py-8">{children}</div>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
