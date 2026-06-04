"use client";

import type { ReactNode } from "react";
import { Auth0Provider as Auth0ClientProvider } from "@auth0/nextjs-auth0/client";

export function Auth0Provider({ children }: { children: ReactNode }) {
  return (
    <Auth0ClientProvider profileRoute="/api/auth/profile">
      {children}
    </Auth0ClientProvider>
  );
}
