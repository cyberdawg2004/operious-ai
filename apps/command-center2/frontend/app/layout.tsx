import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Auth0Provider } from "@/components/auth0-provider";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

// Initialize Inter font for a softer, modern aesthetic
const inter = Inter({ 
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://app.operious.com"),
  title: "Operious AI · Command Center",
  description:
    "Deterministic multi-agent operating system for enterprise governed execution infrastructure",
  icons: {
    icon: [{ url: "/icon", type: "image/png" }],
    shortcut: [{ url: "/icon", type: "image/png" }],
    apple: [{ url: "/icon", type: "image/png" }],
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
      className={`${inter.variable} h-full antialiased bg-canvas`}
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