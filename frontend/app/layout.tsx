import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Cormorant_SC, Cormorant, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Navigation } from "@/components/navigation";

const cormorantSC = Cormorant_SC({
  variable: "--font-cormorant-sc",
  subsets: ["latin"],
  weight: ["600", "700"],
});

const cormorant = Cormorant({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
});

const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-ibm-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
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
      className={`${GeistSans.variable} ${GeistMono.variable} ${cormorantSC.variable} ${cormorant.variable} ${ibmPlexMono.variable} h-full antialiased bg-canvas`}
    >
      <body className="min-h-full flex flex-col bg-canvas text-ink-primary">
        <Navigation />
        {children}
      </body>
    </html>
  );
}
