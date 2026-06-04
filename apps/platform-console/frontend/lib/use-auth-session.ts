"use client";

import { useCallback } from "react";
import { readCurrentPrincipal, type AuthPrincipal } from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";

export type AuthSessionState = {
  principal: AuthPrincipal | null;
  error: string | null;
  isLoading: boolean;
  reload: () => void;
};

export function useAuthSession(): AuthSessionState {
  const loadPrincipal = useCallback(() => readCurrentPrincipal(), []);
  const { data, error, isLoading, reload } = useApiResource(loadPrincipal);
  return { principal: data, error, isLoading, reload };
}
