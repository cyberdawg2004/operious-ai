"use client";

import { AlertTriangle, Database, Loader2, PlugZap } from "lucide-react";

type DataStateProps = {
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
};

export function LoadingState({ label = "Loading operational data..." }: { label?: string }) {
  return (
    <div className="flex min-h-[220px] items-center justify-center rounded-lg border border-border-subtle bg-surface">
      <div className="flex items-center gap-3 text-ink-secondary">
        <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.5} />
        <span className="font-technical text-[12px] uppercase tracking-[0.14em]">
          {label}
        </span>
      </div>
    </div>
  );
}

export function ErrorState({ title, message, actionLabel = "Retry", onAction }: DataStateProps) {
  return (
    <DataStateFrame
      icon={<AlertTriangle className="h-5 w-5 text-red-alert" strokeWidth={1.5} />}
      title={title}
      message={message}
      actionLabel={actionLabel}
      onAction={onAction}
    />
  );
}

export function EmptyState({ title, message, actionLabel, onAction }: DataStateProps) {
  return (
    <DataStateFrame
      icon={<Database className="h-5 w-5 text-ink-tertiary" strokeWidth={1.5} />}
      title={title}
      message={message}
      actionLabel={actionLabel}
      onAction={onAction}
    />
  );
}

export function PendingIntegrationState({ title, message, actionLabel, onAction }: DataStateProps) {
  return (
    <DataStateFrame
      icon={<PlugZap className="h-5 w-5 text-warning-amber" strokeWidth={1.5} />}
      title={title}
      message={message}
      actionLabel={actionLabel}
      onAction={onAction}
    />
  );
}

function DataStateFrame({
  icon,
  title,
  message,
  actionLabel,
  onAction,
}: DataStateProps & { icon: React.ReactNode }) {
  return (
    <div className="flex min-h-[220px] items-center justify-center rounded-lg border border-border-subtle bg-surface px-6 py-10">
      <div className="max-w-[520px] text-center">
        <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded border border-border-subtle bg-surface-raised">
          {icon}
        </div>
        <h2 className="font-display text-[24px] font-semibold text-ink-primary">
          {title}
        </h2>
        <p className="mt-2 text-[14px] leading-relaxed text-ink-secondary">
          {message}
        </p>
        {actionLabel && onAction && (
          <button
            onClick={onAction}
            className="mt-5 rounded border border-border-subtle bg-surface-raised px-4 py-2 text-[13px] font-medium text-ink-primary transition-colors hover:border-border-defined hover:bg-surface-sunken"
          >
            {actionLabel}
          </button>
        )}
      </div>
    </div>
  );
}
