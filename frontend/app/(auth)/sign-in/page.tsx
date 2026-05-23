"use client";

import Link from "next/link";
import { KernelSeal } from "@/components/kernel-seal";

export default function SignInPage() {
  return (
    <div className="w-full max-w-[420px] mx-4">
      {/* Auth Card */}
      <div
        className="rounded-[4px] p-8"
        style={{
          backgroundColor: "var(--cc-bg-surface)",
          border: "1px solid var(--cc-border-subtle)",
        }}
      >
        {/* Logo and Branding */}
        <div className="flex flex-col items-center mb-6">
          <KernelSeal size={48} phase={3} />
          <h1
            className="mt-4 text-[28px] font-semibold tracking-[-0.01em]"
            style={{
              fontFamily: "var(--font-cormorant-sc)",
              color: "var(--cc-text-primary)",
            }}
          >
            Operious
          </h1>
          <p
            className="mt-2 text-[11px] uppercase tracking-[0.18em]"
            style={{
              fontFamily: "var(--font-ibm-plex-mono)",
              color: "var(--cc-text-muted)",
            }}
          >
            Governed Operational Intelligence
          </p>
        </div>

        {/* Divider */}
        <div
          className="h-px w-full mb-6"
          style={{ backgroundColor: "var(--cc-border-subtle)" }}
        />

        {/* SSO Button */}
        <Link
          href="/api/auth/login"
          className="flex items-center justify-center w-full h-12 rounded-[4px] text-[15px] font-semibold tracking-wide transition-colors duration-150"
          style={{
            fontFamily: "var(--font-cormorant-sc)",
            backgroundColor: "var(--cc-gold-primary)",
            color: "var(--cc-bg-deep)",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = "var(--cc-gold-hover)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = "var(--cc-gold-primary)";
          }}
        >
          Sign in with SSO
        </Link>

        {/* Request Access Link */}
        <div className="mt-4 text-center">
          <Link
            href="/request-access"
            className="text-[13px] transition-colors duration-150"
            style={{
              fontFamily: "var(--font-geist-sans)",
              color: "var(--cc-text-muted)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "var(--cc-gold-primary)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "var(--cc-text-muted)";
            }}
          >
            Request enterprise access →
          </Link>
        </div>

        {/* Divider */}
        <div
          className="h-px w-full mt-6 mb-4"
          style={{ backgroundColor: "var(--cc-border-subtle)" }}
        />

        {/* Security Badge */}
        <p
          className="text-center text-[10px] tracking-wide"
          style={{
            fontFamily: "var(--font-ibm-plex-mono)",
            color: "var(--cc-text-muted)",
          }}
        >
          Secured by Auth0 · End-to-end encrypted
        </p>
      </div>

      {/* Background Ambient Decoration */}
      <div
        className="fixed inset-0 pointer-events-none -z-10"
        style={{
          background: `
            radial-gradient(ellipse 600px 400px at 20% 20%, rgba(201, 168, 76, 0.03) 0%, transparent 70%),
            radial-gradient(ellipse 500px 300px at 80% 80%, rgba(30, 58, 95, 0.04) 0%, transparent 70%)
          `,
        }}
      />
    </div>
  );
}
