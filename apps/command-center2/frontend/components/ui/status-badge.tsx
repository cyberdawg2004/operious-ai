import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type StatusTone = "success" | "info" | "warning" | "danger" | "neutral";

const toneClass: Record<StatusTone, string> = {
  success: "cc-chip-ok",
  info: "cc-chip-info",
  warning: "cc-chip-warn",
  danger: "cc-chip-danger",
  neutral: "cc-chip",
};

/**
 * Soft pill badge for ticket/session/queue status. Replaces raw monospace
 * status strings with a colored, readable label managers can scan at a
 * glance.
 */
export function StatusBadge({
  label,
  tone = "neutral",
  icon: Icon,
  className,
}: {
  label: string;
  tone?: StatusTone;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <span className={cn("cc-chip", toneClass[tone], className)}>
      {Icon && <Icon size={12} strokeWidth={2} />}
      {label}
    </span>
  );
}
