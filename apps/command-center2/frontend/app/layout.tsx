import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Auth0Provider } from "@/components/auth0-provider";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

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
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased bg-canvas dark`}
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
