import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Base card surface for the calm analytics design system: white surface,
 * soft shadow, large rounded corners. Use `Card` for the outer container
 * and the optional `CardHeader`/`CardTitle`/`CardDescription` helpers for a
 * consistent title block above the body content.
 */
export function Card({
  children,
  className,
  hover = false,
}: {
  children: ReactNode;
  className?: string;
  hover?: boolean;
}) {
  return (
    <div className={cn("cc-card cc-card-pad", hover && "cc-card-hover", className)}>
      {children}
    </div>
  );
}

export function CardHeader({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-4 flex items-start justify-between gap-3", className)}>
      {children}
    </div>
  );
}

export function CardTitle({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <h3 className={cn("heading-section", className)}>{children}</h3>;
}

export function CardDescription({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <p className={cn("text-meta mt-0.5", className)}>{children}</p>;
}
