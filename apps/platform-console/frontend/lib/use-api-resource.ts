"use client";

import { useCallback, useEffect, useReducer, useState } from "react";
import { formatApiError } from "@/lib/api";

type ResourceState<T> = {
  data: T | null;
  error: string | null;
  isLoading: boolean;
  reload: () => void;
};

export function useApiResource<T>(load: () => Promise<T>): ResourceState<T> {
  type State = {
    data: T | null;
    error: string | null;
    isLoading: boolean;
  };
  type Action =
    | { type: "loading" }
    | { type: "success"; data: T }
    | { type: "error"; error: string };

  const [state, dispatch] = useReducer(
    (current: State, action: Action): State => {
      switch (action.type) {
        case "loading":
          return { ...current, error: null, isLoading: true };
        case "success":
          return { data: action.data, error: null, isLoading: false };
        case "error":
          return { data: null, error: action.error, isLoading: false };
      }
    },
    { data: null, error: null, isLoading: true }
  );
  const [revision, setRevision] = useState(0);

  const reload = useCallback(() => {
    setRevision((value) => value + 1);
  }, []);

  useEffect(() => {
    let active = true;
    dispatch({ type: "loading" });

    load()
      .then((result) => {
        if (!active) return;
        dispatch({ type: "success", data: result });
      })
      .catch((caught: unknown) => {
        if (!active) return;
        dispatch({ type: "error", error: formatApiError(caught) });
      });

    return () => {
      active = false;
    };
  }, [load, revision]);

  return { ...state, reload };
}
