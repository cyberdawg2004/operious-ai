"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Collapsible disclosure for raw/technical content (JSON payloads, parsed
 * config, span dumps). Keeps the default operator view clean and operational
 * while leaving an explicit, one-click path to the underlying detail for
 * engineers and auditors. Collapsed by default.
 */
export function TechnicalDetails({
  label = "Show technical details",
  openLabel = "Hide technical details",
  children,
  className,
  defaultOpen = false,
}: {
  label?: string;
  openLabel?: string;
  children: React.ReactNode;
  className?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={cn("mt-3", className)}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-md border border-border-subtle bg-surface-raised px-2.5 py-1 font-technical text-[10.5px] font-medium uppercase tracking-[0.12em] text-ink-tertiary transition-colors hover:border-border-defined hover:text-ink-secondary"
      >
        <ChevronRight
          size={12}
          strokeWidth={1.9}
          className={cn("transition-transform duration-150", open && "rotate-90")}
        />
        {open ? openLabel : label}
      </button>
      {open && <div className="mt-2 animate-cc-fade-in">{children}</div>}
    </div>
  );
}
