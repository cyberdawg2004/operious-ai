import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { IBM_Plex_Mono } from "next/font/google";
import { Auth0Provider } from "@/components/auth0-provider";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-mono-technical",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://app.operious.com"),
  title: "Operious AI - Command Center",
  description: "Deterministic multi-agent operating system for enterprise governed execution infrastructure",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${ibmPlexMono.variable} h-full antialiased bg-canvas dark`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-canvas text-ink-primary font-sans">
        <Auth0Provider>
          <ThemeProvider>{children}</ThemeProvider>
        </Auth0Provider>
      </body>
    </html>
  );
}
