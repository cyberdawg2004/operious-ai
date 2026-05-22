'use client';

import {
  AnimatePresence,
  motion as fm,
  useReducedMotion,
} from 'framer-motion';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useRouter } from 'next/navigation';
import { Command } from 'cmdk';
import { Search, ArrowRight } from 'lucide-react';
import { NAVIGATION } from '@/lib/navigation';
import { cn } from '@/lib/cn';
import { easings, ms } from '@/lib/motion';

/**
 * Command palette (Cmd+K / Ctrl+K).
 *
 * Fuzzy-searches:
 *   \u2022 Primary navigation entries (always present)
 *   \u2022 Recent actions (NOT YET WIRED \u2014 a session-local registry will land
 *     once the operations queue feeds it explicit "claim" / "approve"
 *     verbs into this store)
 *
 * The palette is keyboard-first. `cmdk` handles arrow / enter navigation;
 * we hook into router.push for selection.
 */

interface PaletteContextValue {
  readonly isOpen: boolean;
  readonly open: () => void;
  readonly close: () => void;
}

const PaletteContext = createContext<PaletteContextValue>({
  isOpen: false,
  open: () => {
    /* noop */
  },
  close: () => {
    /* noop */
  },
});

export const useCommandPalette = () => useContext(PaletteContext);

interface ProviderProps {
  readonly children: ReactNode;
}

export const CommandPaletteProvider = ({ children }: ProviderProps) => {
  const [open, setOpen] = useState(false);
  const reduceMotion = useReducedMotion() ?? false;
  const router = useRouter();

  const close = useCallback(() => setOpen(false), []);
  const openPalette = useCallback(() => setOpen(true), []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const cmd = event.metaKey || event.ctrlKey;
      if (cmd && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const value = useMemo<PaletteContextValue>(
    () => ({ isOpen: open, open: openPalette, close }),
    [open, openPalette, close],
  );

  return (
    <PaletteContext.Provider value={value}>
      {children}
      <AnimatePresence>
        {open ? (
          <fm.div
            className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]"
            initial={{ opacity: 1 }}
            exit={{ opacity: 1 }}
          >
            <fm.button
              type="button"
              aria-label="Close command palette"
              onClick={close}
              initial={{ opacity: 0, backdropFilter: 'blur(0px)' }}
              animate={{ opacity: 0.5, backdropFilter: 'blur(8px)' }}
              exit={{ opacity: 0, backdropFilter: 'blur(0px)' }}
              transition={{
                duration: reduceMotion ? 0 : ms(160),
                ease: easings.precise,
              }}
              className="absolute inset-0 bg-fg"
            />
            <fm.div
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={{
                duration: reduceMotion ? 0 : ms(200),
                ease: easings.precise,
              }}
              className={cn(
                'relative w-full max-w-xl overflow-hidden rounded-lg',
                'border border-line bg-bg-inset shadow-dropdown',
              )}
            >
          <Command
            label="Command palette"
            className="w-full"
          >
            <div className="flex items-center gap-2 border-b border-line px-4">
              <Search className="h-4 w-4 text-fg-dim" />
              <Command.Input
                placeholder="Search actions, tickets, documents\u2026"
                className={cn(
                  'flex-1 bg-transparent py-3 text-sm text-fg outline-none',
                  'placeholder:text-fg-dim',
                )}
              />
              <kbd className="rounded-sm border border-line bg-bg-raised px-1.5 py-0.5 font-mono text-2xs text-fg-subtle">
                Esc
              </kbd>
            </div>
            <Command.List className="max-h-[60vh] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-mono text-fg-subtle">
                No matches.
              </Command.Empty>

              <Command.Group
                heading="Navigate"
                className={cn(
                  '[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5',
                  '[&_[cmdk-group-heading]]:text-mono [&_[cmdk-group-heading]]:text-fg-dim',
                )}
              >
                {NAVIGATION.map((entry) => {
                  const Icon = entry.icon;
                  return (
                    <Command.Item
                      key={entry.href}
                      value={`${entry.label} ${entry.description ?? ''}`}
                      onSelect={() => {
                        router.push(entry.href);
                        close();
                      }}
                      className={cn(
                        'flex cursor-pointer items-center gap-3 rounded-sm px-2 py-2',
                        'text-sm text-fg-muted transition-colors',
                        'data-[selected=true]:bg-bg-raised data-[selected=true]:text-fg',
                      )}
                    >
                      <Icon className="h-4 w-4 text-fg-dim" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate">{entry.label}</p>
                        {entry.description ? (
                          <p className="truncate text-2xs text-fg-subtle">
                            {entry.description}
                          </p>
                        ) : null}
                      </div>
                      <kbd className="rounded-sm border border-line bg-bg-raised px-1 font-mono text-2xs text-fg-dim">
                        G{entry.shortcut.toUpperCase()}
                      </kbd>
                      <ArrowRight className="h-3 w-3 text-fg-dim" />
                    </Command.Item>
                  );
                })}
              </Command.Group>
            </Command.List>

            <footer className="flex items-center justify-between border-t border-line bg-bg-raised px-3 py-1.5 text-mono text-fg-dim">
              <span>
                <kbd className="mr-1 rounded-sm border border-line bg-bg-inset px-1">\u2191\u2193</kbd>
                navigate
              </span>
              <span>
                <kbd className="mr-1 rounded-sm border border-line bg-bg-inset px-1">\u23ce</kbd>
                select
              </span>
            </footer>
          </Command>
            </fm.div>
          </fm.div>
        ) : null}
      </AnimatePresence>
    </PaletteContext.Provider>
  );
};
