'use client';

import { useEffect, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { NAVIGATION } from '@/lib/navigation';

/**
 * Global keyboard shortcuts.
 *
 * Linear-style "G then <key>" sequence for top-level navigation. The first
 * "G" arms a 1200ms window; the second key navigates if it matches a
 * registered shortcut.
 *
 * Cmd+K is handled inside the command palette provider.
 *
 * Sequences are suppressed when the user is typing in an input, textarea,
 * contentEditable, or any element with `data-suppress-shortcuts`.
 */

const isTypingTarget = (target: EventTarget | null): boolean => {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  if (target.isContentEditable) return true;
  if (target.closest('[data-suppress-shortcuts]')) return true;
  return false;
};

interface ProviderProps {
  readonly children: ReactNode;
}

export const KeyboardShortcutProvider = ({ children }: ProviderProps) => {
  const router = useRouter();

  useEffect(() => {
    let armed = false;
    let timer: number | null = null;

    const arm = () => {
      armed = true;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        armed = false;
        timer = null;
      }, 1200);
    };

    const disarm = () => {
      armed = false;
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };

    const handler = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;

      const key = event.key.toLowerCase();
      if (!armed && key === 'g') {
        arm();
        return;
      }
      if (armed) {
        const match = NAVIGATION.find((entry) => entry.shortcut === key);
        if (match) {
          event.preventDefault();
          router.push(match.href);
        }
        disarm();
      }
    };

    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [router]);

  return <>{children}</>;
};
