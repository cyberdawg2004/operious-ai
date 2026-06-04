"use client";

import { ShieldCheck } from "lucide-react";

export default function SignInPage() {
  const handleLogin = () => {
    const currentUrl = new URL(window.location.href);
    const returnTo = currentUrl.searchParams.get("returnTo") || "/tenants";
    const loginUrl = new URL("/api/auth/login", window.location.origin);
    loginUrl.searchParams.set("returnTo", returnTo);
    window.location.href = loginUrl.toString();
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10">
      <section className="w-full max-w-md rounded-lg border border-border-subtle bg-surface-raised p-6 shadow-2xl sm:p-8">
        <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
          Operious
        </div>
        <div className="mt-6 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded border border-gold-primary/30 bg-gold-primary/10 text-gold-primary">
            <ShieldCheck className="h-5 w-5" strokeWidth={1.7} />
          </span>
          <div>
            <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
              Platform Operations Access
            </div>
            <h1 className="mt-1 text-[24px] font-semibold text-ink-primary">
              Sign in to Platform Console
            </h1>
          </div>
        </div>
        <p className="mt-4 text-[13px] leading-relaxed text-ink-secondary">
          Restricted to Operious platform administrators. Tenant operators should use
          the tenant Command Center.
        </p>
        <button
          type="button"
          onClick={handleLogin}
          className="mt-8 flex h-11 w-full items-center justify-center rounded bg-ink-primary px-4 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
        >
          Sign in with SSO
        </button>
      </section>
    </main>
  );
}
