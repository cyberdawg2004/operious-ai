"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Building2, LogOut, ShieldCheck, UserPlus } from "lucide-react";
import type { AuthPrincipal } from "@/lib/api";

/**
 * Lean platform shell. Intentionally NOT the tenant Command Center
 * dashboard-shell — no action-approval / semantic-circuit / crisis polls
 * (those are tenant concerns). Just a header, minimal nav, and sign-out.
 */
export function PlatformShell({
  principal,
  children,
}: {
  principal: AuthPrincipal | null;
  children: ReactNode;
}) {
  const signOut = () => {
    window.location.href = "/api/auth/logout-sign-in";
  };

  return (
    <div className="min-h-screen bg-canvas text-ink-primary lg:flex">
      <aside className="w-full shrink-0 border-b border-border-subtle bg-surface lg:h-screen lg:w-[232px] lg:border-b-0 lg:border-r">
        <div className="px-4 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded border border-gold-primary/30 bg-gold-primary/10 text-gold-primary">
              <ShieldCheck className="h-4 w-4" strokeWidth={1.8} />
            </span>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
                Operious
              </div>
              <div className="text-[14px] font-semibold text-ink-primary">
                Platform Console
              </div>
            </div>
          </div>
        </div>
        <nav className="px-3 py-2">
          <h4 className="mb-1.5 px-2 font-technical text-[10px] font-semibold uppercase tracking-[0.18em] text-ink-quaternary">
            Platform
          </h4>
          <ul className="space-y-0.5">
            <li>
              <Link
                href="/tenants"
                className="flex items-center gap-2 rounded-md px-2 py-2 text-[13px] text-ink-secondary hover:bg-surface-raised hover:text-ink-primary"
              >
                <Building2 className="h-4 w-4" strokeWidth={1.8} />
                Tenants
              </Link>
            </li>
            <li>
              <Link
                href="/onboarding"
                className="flex items-center gap-2 rounded-md px-2 py-2 text-[13px] text-ink-secondary hover:bg-surface-raised hover:text-ink-primary"
              >
                <UserPlus className="h-4 w-4" strokeWidth={1.8} />
                Onboard Tenant
              </Link>
            </li>
          </ul>
        </nav>
      </aside>

      <div className="min-w-0 flex-1 lg:flex lg:min-h-screen lg:flex-col">
        <header className="sticky top-0 z-30 border-b border-border-subtle bg-surface/90 backdrop-blur">
          <div className="flex min-h-[56px] items-center justify-between gap-3 px-4 py-2.5 sm:px-6 lg:px-8">
            <div className="font-technical text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
              Command Center / <span className="text-gold-primary">Platform</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="hidden max-w-[200px] truncate font-mono text-[11px] text-ink-tertiary sm:block">
                {principal?.principal_id ?? "platform operator"}
              </span>
              <button
                type="button"
                onClick={signOut}
                className="flex h-8 items-center gap-2 rounded-md border border-border-subtle bg-surface px-2.5 text-[12px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
              >
                <LogOut className="h-3.5 w-3.5" strokeWidth={1.8} />
                Sign out
              </button>
            </div>
          </div>
        </header>
        <div className="animate-cc-fade-in">{children}</div>
      </div>
    </div>
  );
}
