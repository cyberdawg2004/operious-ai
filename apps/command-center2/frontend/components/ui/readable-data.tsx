"use client";

import { Download } from "lucide-react";
import { cn } from "@/lib/utils";

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    if (value.every((item) => typeof item !== "object" || item === null)) {
      return value.join(", ");
    }
    return `${value.length} item${value.length === 1 ? "" : "s"}`;
  }
  return String(value);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function renderEntries(data: Record<string, unknown>, depth: number) {
  return Object.entries(data).map(([key, value]) => {
    if (isPlainObject(value) && Object.keys(value).length > 0) {
      return (
        <div key={key} style={{ marginLeft: depth * 16 }}>
          <dt className="font-medium text-ink-primary">{humanizeKey(key)}</dt>
          <dd className="mt-1 space-y-1.5">{renderEntries(value, depth + 1)}</dd>
        </div>
      );
    }
    return (
      <div key={key} className="flex flex-wrap gap-x-2 gap-y-0.5" style={{ marginLeft: depth * 16 }}>
        <dt className="shrink-0 text-ink-tertiary">{humanizeKey(key)}:</dt>
        <dd className="break-all text-ink-body">{formatValue(value)}</dd>
      </div>
    );
  });
}

/**
 * Renders a JSON-shaped payload as readable key/value text instead of a raw
 * code block. Nested objects are indented; arrays and empty values are
 * summarized in plain language. Use alongside `DownloadableLog` when the
 * raw form is needed.
 */
export function CodeAsReadableText({
  data,
  className,
}: {
  data: Record<string, unknown>;
  className?: string;
}) {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return <p className={cn("text-meta", className)}>No details available.</p>;
  }
  return <dl className={cn("space-y-1.5 text-body", className)}>{renderEntries(data, 0)}</dl>;
}

/**
 * Offers the raw form of a payload as a downloadable file rather than an
 * on-screen code block — satisfies the "no raw JSON in the UI" rule while
 * keeping the underlying detail available for engineers/auditors.
 */
export function DownloadableLog({
  data,
  filename,
  label = "Download raw log",
  className,
}: {
  data: unknown;
  filename: string;
  label?: string;
  className?: string;
}) {
  const handleDownload = () => {
    const content = typeof data === "string" ? data : JSON.stringify(data, null, 2);
    const blob = new Blob([content], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <button type="button" onClick={handleDownload} className={cn("cc-btn cc-btn-secondary", className)}>
      <Download size={13} strokeWidth={2} />
      {label}
    </button>
  );
}
