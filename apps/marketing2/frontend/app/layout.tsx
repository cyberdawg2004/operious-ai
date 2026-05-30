import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Playfair_Display, Inter } from "next/font/google";
import { MarketingLayout } from "@/components/marketing-layout";
import { CookieConsent } from "@/components/cookie-consent";
import "./globals.css";

const playfair = Playfair_Display({
  subsets: ["latin"],
  weight: ["700", "800", "900"],
  style: ["normal", "italic"],
  variable: "--font-playfair",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://www.operious.com"),
  title: "Operious AI — Operational Governance Infrastructure",
  description:
    "Enterprise operational workflows with enforced policy, complete governance, and a forensic record of every decision made.",
  icons: {
    icon: [{ url: "/icon", type: "image/png" }],
    shortcut: [{ url: "/icon", type: "image/png" }],
    apple: [{ url: "/icon", type: "image/png" }],
  },
  openGraph: {
    title: "Operious AI",
    description:
      "Operational governance infrastructure for enterprise support, warranty, claims, escalations, and approvals.",
    url: "https://www.operious.com",
    siteName: "Operious AI",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Operious AI — Operational Governance Infrastructure",
    description:
      "Enterprise workflows that scale. Decisions that hold up in any audit.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} ${playfair.variable} ${inter.variable} h-full antialiased bg-canvas`}
    >
      <body className="min-h-full flex flex-col bg-canvas text-ink-primary">
        <MarketingLayout>{children}</MarketingLayout>
        <CookieConsent />
      </body>
    </html>
  );
}
