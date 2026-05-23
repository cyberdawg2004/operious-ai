import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { MarketingLayout } from "@/components/marketing-layout";
import { CookieConsent } from "@/components/cookie-consent";

const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-ibm-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Operious AI | Deterministic Multi-Agent Operating System",
  description:
    "Enterprise governed execution infrastructure for Fortune 500 companies in regulated industries.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} ${ibmPlexMono.variable} h-full antialiased bg-canvas`}
    >
      <body className="min-h-full flex flex-col bg-canvas text-ink-primary">
        <MarketingLayout>{children}</MarketingLayout>
        <CookieConsent />
      </body>
    </html>
  );
}
