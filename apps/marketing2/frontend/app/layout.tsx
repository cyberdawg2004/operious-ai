import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Playfair_Display, Inter } from "next/font/google";
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
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});
import { MarketingLayout } from "@/components/marketing-layout";
import { CookieConsent } from "@/components/cookie-consent";

export const metadata: Metadata = {
  metadataBase: new URL("https://www.operious.com"),
  title: "Operious AI — Governed Execution Infrastructure",
  description:
    "The layer between what AI proposes and what your " +
    "business executes. Governed. Audited. Immutable.",
  icons: {
    icon: [{ url: "/icon", type: "image/png" }],
    shortcut: [{ url: "/icon", type: "image/png" }],
    apple: [{ url: "/icon", type: "image/png" }],
  },
  openGraph: {
    title: "Operious AI",
    description:
      "Governed AI execution infrastructure. " +
      "The containment layer between AI models and your business.",
    url: "https://www.operious.com",
    siteName: "Operious AI",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Operious AI — Governed Execution Infrastructure",
    description:
      "The containment layer between AI models and your business.",
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
