"use client";

import type { ReactNode } from "react";
import { UserProvider } from "@auth0/nextjs-auth0/client";

export function Auth0Provider({ children }: { children: ReactNode }) {
  return <UserProvider>{children}</UserProvider>;
}
