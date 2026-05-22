'use client';

import { create } from 'zustand';
import type { TenantId } from '@operious/types';
import { brand } from '@operious/shared';

/**
 * Tenant store.
 *
 * The frontend does NOT decide which tenant a principal may access \u2014 that
 * authority lives with the backend's tenant axis on the verified
 * `AuthorityContext`. The store is purely presentational: which of the
 * already-authorised tenants the operator is currently inspecting.
 *
 * Switching tenant clears the entire TanStack Query cache to enforce the
 * tenant-isolation acceptance criterion: stale data from tenant A must
 * never bleed into a tenant B render.
 */

interface TenantState {
  readonly currentTenantId: TenantId | null;
  readonly availableTenantIds: readonly TenantId[];
  readonly setCurrent: (id: TenantId) => void;
  readonly setAvailable: (ids: readonly TenantId[]) => void;
}

export const useTenantStore = create<TenantState>((set) => ({
  currentTenantId: null,
  availableTenantIds: [],
  setCurrent: (id) => set({ currentTenantId: id }),
  setAvailable: (ids) =>
    set((state) => {
      // If there is no current tenant yet, pick the first authorised one.
      if (!state.currentTenantId && ids.length > 0) {
        return { availableTenantIds: ids, currentTenantId: ids[0] };
      }
      return { availableTenantIds: ids };
    }),
}));

/** Convenience constructor for tests / dev seeds. */
export const tenant = (id: string): TenantId => brand<'TenantId'>(id);
