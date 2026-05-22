'use client';

import { AnimatePresence, motion as fm, useReducedMotion } from 'framer-motion';
import { KernelSeal } from '@/components/brand/kernel-seal';
import { easings, ms, TENANT_CEREMONY } from '@/lib/motion';

interface TenantCeremonyProps {
  readonly active: boolean;
  readonly tenantName: string;
}

/**
 * Tenant switcher ceremony.
 *
 * Switching tenants is a constitutional act — every cached read from
 * the previous tenant is invalidated. We mark the moment with a brief
 * full-screen overlay (KernelSeal rotates once, the tenant label is
 * announced in mono).
 *
 * Spec: overlay fades in over 200ms, seal rotates 360° over 800ms,
 * overlay fades out after the new tenant context loads.
 */
export const TenantCeremony = ({ active, tenantName }: TenantCeremonyProps) => {
  const reduceMotion = useReducedMotion() ?? false;
  return (
    <AnimatePresence>
      {active ? (
        <fm.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{
            duration: reduceMotion ? 0 : ms(TENANT_CEREMONY.overlayInMs),
            ease: easings.precise,
          }}
          className="fixed inset-0 z-[80] flex flex-col items-center justify-center gap-6 bg-fg/60 backdrop-blur-md"
          role="status"
          aria-live="polite"
        >
          <fm.div
            initial={{ rotate: 0 }}
            animate={
              reduceMotion ? { rotate: 0 } : { rotate: 360 }
            }
            transition={{
              duration: reduceMotion ? 0 : ms(TENANT_CEREMONY.sealRotateMs),
              ease: easings.expoInOut,
            }}
          >
            <KernelSeal size={96} />
          </fm.div>
          <fm.p
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: ms(TENANT_CEREMONY.contentInMs),
              ease: easings.precise,
              delay: ms(120),
            }}
            className="data-l text-bg-inset text-center"
          >
            Switching to{' '}
            <span className="text-accent-glow">{tenantName}</span>
          </fm.p>
          <fm.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: ms(400), delay: ms(240) }}
            className="eyebrow text-bg-inset/70 text-center"
          >
            REHYDRATING TENANT CONTEXT
          </fm.p>
        </fm.div>
      ) : null}
    </AnimatePresence>
  );
};
