'use client';

import { useEffect, useState } from 'react';
import { KernelSeal } from '../brand/kernel-seal';
import { SubstrateChat } from './substrate-chat';

/**
 * FloatingChat — bottom-right circular launcher.
 *
 * Always visible. On click expands to a 400x600 chat panel that uses the
 * same SubstrateChat surface as Section 7 — same server action, same
 * runtime, same governance bounds.
 */
export const FloatingChat = () => {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    if (open) window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <div className="pointer-events-none fixed inset-0 z-[60]">
      {open ? (
        <div
          className="pointer-events-auto absolute bottom-24 right-6 w-[min(400px,calc(100vw-2rem))]"
          style={{ height: 'min(600px, calc(100vh - 8rem))' }}
        >
          <SubstrateChat
            variant="floating"
            className="h-full"
            headerLabel="Operious Substrate"
            suggestions={[
              'How does fail-closed governance work?',
              'What does tenant isolation prevent?',
            ]}
          />
        </div>
      ) : null}

      <button
        type="button"
        aria-label={open ? 'Close substrate chat' : 'Open substrate chat'}
        onClick={() => setOpen((value) => !value)}
        data-cursor="interactive"
        className="pointer-events-auto absolute bottom-6 right-6 inline-flex h-12 w-12 items-center justify-center rounded-full bg-ink-primary text-canvas-surface shadow-modal transition-transform duration-[200ms] ease-[cubic-bezier(0.22,1,0.36,1)] hover:scale-[1.04] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-gold-highlight"
      >
        {open ? (
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
            <path d="M6 6l12 12M6 18L18 6" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        ) : (
          <KernelSeal size={28} variant="dark" animated={false} />
        )}
      </button>
    </div>
  );
};

export default FloatingChat;
