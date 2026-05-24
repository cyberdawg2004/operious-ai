"use client";

import { useCallback, useEffect } from "react";
import {
  getConfiguredOperatorLabel,
  readCurrentPrincipal,
  type AuthPrincipal,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";

export type AuthSessionState = {
  principal: AuthPrincipal | null;
  error: string | null;
  isLoading: boolean;
  reload: () => void;
  operatorLabel: string;
};

export function useAuthSession(): AuthSessionState {
  const loadPrincipal = useCallback(() => readCurrentPrincipal(), []);
  const { data, error, isLoading, reload } = useApiResource(loadPrincipal);

  useEffect(() => {
    if (!data || typeof window === "undefined") return;
    if (data.tenant_id) window.localStorage.setItem("operious_tenant_id", data.tenant_id);
    if (data.principal_id) {
      window.localStorage.setItem("operious_principal_id", data.principal_id);
      window.localStorage.setItem("operious_operator_label", data.principal_id);
    }
  }, [data]);

  return {
    principal: data,
    error,
    isLoading,
    reload,
    operatorLabel: data?.principal_id ?? getConfiguredOperatorLabel(),
  };
}
