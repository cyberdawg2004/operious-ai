'use client';

import { useEffect, useRef, useState } from 'react';
import { LogOut, LogIn, User } from 'lucide-react';
import { useUser } from '@auth0/nextjs-auth0/client';
import { useSession } from '@/lib/auth0-bridge';
import { cn } from '@/lib/cn';

/**
 * User menu \u2014 anchored at the bottom of the sidebar.
 *
 * Renders three distinct states:
 *   \u2022 Auth0 not configured \u2192 prompts the operator to configure env vars.
 *   \u2022 Authenticated         \u2192 avatar + display name + role badges + logout.
 *   \u2022 Anonymous             \u2192 "Sign in" CTA pointing at /api/auth/login.
 *
 * Roles are surfaced verbatim from the backend `/me` capability list \u2014 the
 * frontend never derives roles from the Auth0 user object.
 */
export const UserMenu = () => {
  const { user } = useUser();
  const { isAuth0Configured, isAuthenticated, principal } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  if (!isAuth0Configured) {
    return (
      <div className="space-y-1.5 rounded-sm border border-line bg-bg px-2.5 py-2">
        <p className="text-mono text-fg-dim">auth0</p>
        <p className="font-mono text-2xs text-fg-subtle">not configured</p>
      </div>
    );
  }

  if (!isAuthenticated || !principal) {
    return (
      <a
        href="/api/auth/login"
        className={cn(
          'flex items-center gap-2 rounded-sm border border-line bg-bg px-2.5 py-2',
          'font-mono text-xs text-fg-muted transition-colors',
          'hover:border-accent hover:text-fg',
        )}
      >
        <LogIn className="h-3.5 w-3.5 text-accent" />
        sign in
      </a>
    );
  }

  const initial = principal.displayName.charAt(0).toUpperCase();
  const primaryRole = principal.roles[0] ?? 'operator';

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          'flex w-full items-center gap-2.5 rounded-sm border border-line bg-bg px-2.5 py-2 text-left',
          'transition-colors hover:border-line-strong hover:bg-bg-raised',
        )}
      >
        <div
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-sm',
            'bg-accent/15 font-mono text-xs font-medium text-accent',
          )}
        >
          {user?.picture ? (
            // Avatars from Auth0 \u2014 if they fail to load we fall back to the
            // initial above (CSS chained fallback is implicit via the bg).
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={user.picture}
              alt=""
              className="h-full w-full rounded-sm object-cover"
            />
          ) : (
            <span>{initial}</span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-xs text-fg">
            {principal.displayName}
          </p>
          <p className="truncate font-mono text-2xs text-fg-subtle">
            {primaryRole}
          </p>
        </div>
      </button>
      {open ? (
        <div
          className={cn(
            'absolute bottom-full left-0 right-0 z-40 mb-1',
            'rounded-md border border-line bg-bg-inset shadow-raised',
            'animate-fade-in py-1',
          )}
        >
          <div className="border-b border-line px-2.5 py-2">
            <p className="text-mono text-fg-dim">signed in as</p>
            <p className="truncate font-mono text-xs text-fg">
              {principal.email ?? principal.displayName}
            </p>
          </div>
          <button
            type="button"
            disabled
            className="flex w-full items-center gap-2 px-2.5 py-1.5 font-mono text-xs text-fg-dim"
          >
            <User className="h-3 w-3" />
            account (soon)
          </button>
          <a
            href="/api/auth/logout"
            className={cn(
              'flex w-full items-center gap-2 px-2.5 py-1.5',
              'font-mono text-xs text-fg-muted transition-colors',
              'hover:bg-bg-raised hover:text-fg',
            )}
          >
            <LogOut className="h-3 w-3" />
            sign out
          </a>
        </div>
      ) : null}
    </div>
  );
};
