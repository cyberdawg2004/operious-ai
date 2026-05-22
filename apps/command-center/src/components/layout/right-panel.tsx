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
import { X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { easings, ms, RIGHT_PANEL } from '@/lib/motion';

/**
 * Right inspection panel.
 *
 * Slides in from the right edge, 480px wide, full-height. Used by every
 * page for detail views.
 *
 * Spec choreography (see Visual Execution Hyperprompt):
 *   Open    : translateX(100%) → 0, opacity 0 → 1, 320ms ease 'precise'
 *             Backdrop opacity 0 → 0.4 over 240ms
 *             Backdrop blur(0) → blur(8px) over 320ms
 *   Close   : translateX(0) → 100%, opacity 1 → 0, 240ms ease 'precise'
 *             (Exit is always faster than enter.)
 *   Content : Sections stagger-reveal at 60ms intervals starting 120ms
 *             after the panel begins opening.
 *
 * Escape closes any open panel. Backdrop click closes. Reduced motion
 * collapses to an instant transition.
 */

interface PanelContent {
  readonly title: string;
  readonly subtitle?: string;
  readonly body: ReactNode;
  readonly footer?: ReactNode;
  readonly key?: string;
}

interface RightPanelContextValue {
  readonly isOpen: boolean;
  readonly open: (content: PanelContent) => void;
  readonly close: () => void;
}

const RightPanelContext = createContext<RightPanelContextValue>({
  isOpen: false,
  open: () => {},
  close: () => {},
});

export const useRightPanel = () => useContext(RightPanelContext);

interface ProviderProps {
  readonly children: ReactNode;
}

export const RightPanelProvider = ({ children }: ProviderProps) => {
  const reduceMotion = useReducedMotion() ?? false;
  const [content, setContent] = useState<PanelContent | null>(null);

  const close = useCallback(() => setContent(null), []);
  const open = useCallback(
    (next: PanelContent) => setContent(next),
    [],
  );

  const value = useMemo<RightPanelContextValue>(
    () => ({ isOpen: Boolean(content), open, close }),
    [content, open, close],
  );

  useEffect(() => {
    if (!content) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [content, close]);

  return (
    <RightPanelContext.Provider value={value}>
      {children}
      <AnimatePresence>
        {content ? (
          <fm.div
            className="fixed inset-0 z-40 flex"
            initial={{ opacity: 1 }}
            exit={{ opacity: 1 }}
          >
            {/* Backdrop — blur ramps in over 320ms; opacity over 240ms. */}
            <fm.button
              type="button"
              aria-label="Close panel"
              onClick={close}
              initial={{
                opacity: 0,
                backdropFilter: 'blur(0px)',
                WebkitBackdropFilter: 'blur(0px)',
              }}
              animate={
                reduceMotion
                  ? {
                      opacity: 0.4,
                      backdropFilter: 'blur(8px)',
                      WebkitBackdropFilter: 'blur(8px)',
                    }
                  : {
                      opacity: 0.4,
                      backdropFilter: 'blur(8px)',
                      WebkitBackdropFilter: 'blur(8px)',
                    }
              }
              exit={{
                opacity: 0,
                backdropFilter: 'blur(0px)',
                WebkitBackdropFilter: 'blur(0px)',
              }}
              transition={{
                duration: reduceMotion
                  ? 0
                  : ms(RIGHT_PANEL.backdropOpenMs),
                ease: easings.precise,
                backdropFilter: {
                  duration: reduceMotion
                    ? 0
                    : ms(RIGHT_PANEL.backdropBlurMs),
                  ease: easings.precise,
                },
              }}
              className="flex-1 bg-fg/40"
            />
            {/* Panel — 480px, slides from right, scaffolds content stagger. */}
            <fm.aside
              role="dialog"
              aria-modal="true"
              aria-labelledby="right-panel-title"
              initial={{ x: '100%', opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: '100%', opacity: 0 }}
              transition={{
                duration: reduceMotion ? 0 : ms(RIGHT_PANEL.openMs),
                ease: easings.precise,
              }}
              className={cn(
                'flex h-full w-[480px] max-w-[92vw] flex-col',
                'border-l border-line bg-bg-inset shadow-panel',
              )}
            >
              <PanelContentStager
                content={content}
                onClose={close}
                reduceMotion={reduceMotion}
              />
            </fm.aside>
          </fm.div>
        ) : null}
      </AnimatePresence>
    </RightPanelContext.Provider>
  );
};

interface PanelContentStagerProps {
  readonly content: PanelContent;
  readonly onClose: () => void;
  readonly reduceMotion: boolean;
}

/**
 * Sub-component so the stagger transition prop list isn't re-evaluated
 * each render. Stagger starts 120ms after the panel opens; siblings at
 * 60ms intervals (per spec).
 */
const PanelContentStager = ({
  content,
  onClose,
  reduceMotion,
}: PanelContentStagerProps) => {
  const child = {
    hidden: { opacity: 0, y: 8 },
    show: { opacity: 1, y: 0 },
  } as const;
  const container = {
    hidden: {},
    show: {
      transition: {
        delayChildren: reduceMotion
          ? 0
          : ms(RIGHT_PANEL.staggerInitialDelayMs),
        staggerChildren: reduceMotion ? 0 : ms(RIGHT_PANEL.staggerMs),
      },
    },
  } as const;

  return (
    <fm.div
      variants={container}
      initial="hidden"
      animate="show"
      className="flex h-full flex-col"
    >
      <fm.header
        variants={child}
        transition={{ duration: ms(240), ease: easings.precise }}
        className="flex items-start justify-between gap-3 border-b border-line px-8 py-4"
      >
        <div className="min-w-0 flex-1">
          <p className="eyebrow text-fg-dim">inspect</p>
          <h2
            id="right-panel-title"
            className="heading-m text-fg leading-tight"
          >
            {content.title}
          </h2>
          {content.subtitle ? (
            <p className="body-xs text-fg-subtle mt-1">{content.subtitle}</p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className={cn(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-sm',
            'text-fg-subtle transition-colors duration-[160ms] hover:bg-bg-raised hover:text-fg',
          )}
        >
          <X className="h-4 w-4" />
        </button>
      </fm.header>
      <fm.div
        variants={child}
        transition={{ duration: ms(240), ease: easings.precise }}
        className="flex-1 overflow-y-auto px-8 py-6"
      >
        {content.body}
      </fm.div>
      {content.footer ? (
        <fm.footer
          variants={child}
          transition={{ duration: ms(240), ease: easings.precise }}
          className="border-t border-line bg-bg-raised px-8 py-4"
        >
          {content.footer}
        </fm.footer>
      ) : null}
    </fm.div>
  );
};
