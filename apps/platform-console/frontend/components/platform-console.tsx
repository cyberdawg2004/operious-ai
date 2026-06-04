"use client";

import type { ReactNode } from "react";
import { Loader2, Lock, ShieldAlert } from "lucide-react";
import { useAuthSession } from "@/lib/use-auth-session";
import { resolvePlatformAccess } from "@/lib/platform-access";
import { PlatformShell } from "@/components/platform-shell";

/**
 * The gate. Reads /auth/me and renders platform content ONLY for a verified
 * principal holding platform.tenant.admin. Everyone else gets a refusal — a
 * tenant operator who reaches this URL never sees platform tooling.
 */
export function PlatformConsole({ children }: { children: ReactNode }) {
  const { principal, error, isLoading, reload } = useAuthSession();
  const access = resolvePlatformAccess({ principal, error, isLoading });
  const signOutToSignIn = () => {
    window.location.assign("/api/auth/logout-sign-in");
  };

  if (access === "loading") {
    return (
      <CenteredCard>
        <Loader2 className="h-5 w-5 animate-spin text-ink-tertiary" strokeWidth={1.8} />
        <p className="mt-3 text-[13px] text-ink-secondary">Resolving platform authority…</p>
      </CenteredCard>
    );
  }

  if (access === "unauthenticated") {
    return (
      <CenteredCard>
        <Lock className="h-6 w-6 text-ink-tertiary" strokeWidth={1.7} />
        <h1 className="mt-3 text-[20px] font-semibold text-ink-primary">Sign in required</h1>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-secondary">
          This is the Operious platform operations console. Sign in with a platform
          operator account to continue.
        </p>
        <a
          href="/api/auth/login?returnTo=/tenants"
          className="mt-5 inline-flex h-10 items-center justify-center rounded bg-ink-primary px-4 text-[13px] font-medium text-white hover:opacity-90"
        >
          Sign in with SSO
        </a>
      </CenteredCard>
    );
  }

  if (access === "error") {
    return (
      <CenteredCard>
        <ShieldAlert className="h-6 w-6 text-red-alert" strokeWidth={1.7} />
        <h1 className="mt-3 text-[20px] font-semibold text-ink-primary">
          Could not verify authority
        </h1>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-secondary">{error}</p>
        <button
          type="button"
          onClick={reload}
          className="mt-5 inline-flex h-10 items-center justify-center rounded border border-border-subtle px-4 text-[13px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
        >
          Retry
        </button>
      </CenteredCard>
    );
  }

  if (access === "refused") {
    return (
      <CenteredCard>
        <ShieldAlert className="h-6 w-6 text-red-alert" strokeWidth={1.7} />
        <h1 className="mt-3 text-[20px] font-semibold text-ink-primary">Not authorized</h1>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-secondary">
          This is the platform operations console — the surface for Operious platform
          administrators. Your account does not hold the{" "}
          <code className="rounded bg-surface-raised px-1 py-0.5 font-mono text-[12px]">
            platform.tenant.admin
          </code>{" "}
          capability. If you are a tenant operator, use the tenant Command Center instead.
        </p>
        <button
          type="button"
          onClick={signOutToSignIn}
          className="mt-5 inline-flex h-10 items-center justify-center rounded border border-border-subtle px-4 text-[13px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
        >
          Sign out
        </button>
      </CenteredCard>
    );
  }

  // access === "authorized"
  return <PlatformShell principal={principal}>{children}</PlatformShell>;
}

function CenteredCard({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10 text-ink-primary">
      <section className="w-full max-w-md rounded-lg border border-border-subtle bg-surface-raised p-6 text-center sm:p-8">
        <div className="flex flex-col items-center">{children}</div>
      </section>
    </main>
  );
}
