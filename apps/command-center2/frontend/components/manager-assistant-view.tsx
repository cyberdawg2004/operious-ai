"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BarChart2,
  BotMessageSquare,
  Hash,
  Loader2,
  Send,
  UserRound,
} from "lucide-react";
import { ErrorState } from "@/components/data-state";
import {
  queryManagerAssistant,
  type ManagerAssistantChartData,
  type ManagerAssistantResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ChatMessage =
  | { role: "user"; content: string; id: string }
  | { role: "assistant"; content: string; id: string; response: ManagerAssistantResponse };

const SUGGESTED_QUESTIONS = [
  "What's my auto-resolution rate this week?",
  "How many refunds are pending approval?",
  "Which SOPs conflict in my knowledge base?",
  "What's the escalation rate this month?",
  "How many active conversations are there right now?",
  "What's the average QA score this week?",
];

export function ManagerAssistantView() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const send = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || loading) return;
      setDraft("");
      setLoading(true);

      const userId = `user-${Date.now()}`;
      const assistantId = `assistant-${Date.now()}`;

      setMessages((prev) => [
        ...prev,
        { role: "user", content: q, id: userId },
      ]);

      try {
        const response = await queryManagerAssistant(q);
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: response.answer, id: assistantId, response },
        ]);
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : "Request failed. Please try again.";
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: msg,
            id: assistantId,
            response: {
              answer: msg,
              chart_type: "none",
              chart_data: {},
              query_key: "",
              cannot_answer: false,
              invocation_id: assistantId,
            },
          },
        ]);
      } finally {
        setLoading(false);
        inputRef.current?.focus();
      }
    },
    [loading]
  );

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(draft);
    }
  };

  if (fatalError) {
    return (
      <ErrorState
        title="Assistant unavailable"
        message={fatalError}
        onAction={() => setFatalError(null)}
      />
    );
  }

  return (
    <main className="min-w-0 flex-1 overflow-hidden bg-canvas">
      <div className="flex h-[calc(100dvh-64px)] flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-border-subtle px-6 py-3">
          <BotMessageSquare className="h-5 w-5 text-gold-primary" strokeWidth={1.8} />
          <div>
            <div className="text-[14px] font-semibold text-ink-primary">
              Operations Assistant
            </div>
            <div className="text-[11.5px] text-ink-tertiary">
              Ask natural-language questions about your operation — auto-resolution,
              escalations, approvals, SOP conflicts, and more.
            </div>
          </div>
        </div>

        {/* Thread */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {messages.length === 0 ? (
            <EmptyState onSuggest={send} />
          ) : (
            <div className="mx-auto max-w-2xl space-y-5">
              {messages.map((msg) =>
                msg.role === "user" ? (
                  <UserBubble key={msg.id} content={msg.content} />
                ) : (
                  <AssistantBubble key={msg.id} message={msg} />
                )
              )}
              {loading && <TypingIndicator />}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-border-subtle bg-canvas px-6 py-4">
          <div className="mx-auto flex max-w-2xl items-center gap-3">
            <input
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask about your operation…"
              disabled={loading}
              className={cn(
                "min-w-0 flex-1 rounded-lg border border-border-subtle bg-surface px-4 py-2.5",
                "text-[13px] text-ink-primary placeholder:text-ink-quaternary",
                "outline-none transition-colors focus:border-border-defined",
                "disabled:cursor-not-allowed disabled:opacity-60"
              )}
              autoFocus
            />
            <button
              type="button"
              onClick={() => void send(draft)}
              disabled={loading || !draft.trim()}
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
                "border border-border-subtle text-ink-secondary transition-colors",
                "hover:border-border-defined hover:text-ink-primary",
                "disabled:cursor-not-allowed disabled:opacity-40"
              )}
              aria-label="Send"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.8} />
              ) : (
                <Send className="h-4 w-4" strokeWidth={1.8} />
              )}
            </button>
          </div>
          <p className="mx-auto mt-2 max-w-2xl text-center text-[10.5px] text-ink-quaternary">
            Read-only view of your tenant's operational data. All answers are sourced
            from real records — no fabricated numbers.
          </p>
        </div>
      </div>
    </main>
  );
}

// ── Empty / suggestions ───────────────────────────────────────────────────────

function EmptyState({ onSuggest }: { onSuggest: (q: string) => void }) {
  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6 text-center">
        <BotMessageSquare
          className="mx-auto mb-3 h-10 w-10 text-gold-primary opacity-60"
          strokeWidth={1.4}
        />
        <h2 className="text-[15px] font-semibold text-ink-primary">
          Ask about your operation
        </h2>
        <p className="mt-1 text-[12.5px] text-ink-tertiary">
          Try one of these or type your own question below.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onSuggest(q)}
            className={cn(
              "rounded-lg border border-border-subtle bg-surface px-4 py-2.5 text-left",
              "text-[12.5px] text-ink-secondary transition-colors",
              "hover:border-border-defined hover:bg-surface-raised hover:text-ink-primary"
            )}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Message bubbles ───────────────────────────────────────────────────────────

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex items-start justify-end gap-2">
      <div className="max-w-[min(480px,80%)] rounded-lg border border-blue-system/25 bg-blue-system/10 px-4 py-2.5 text-[13px] text-ink-primary">
        {content}
      </div>
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border-subtle bg-surface-raised text-blue-system">
        <UserRound className="h-3.5 w-3.5" strokeWidth={1.8} />
      </div>
    </div>
  );
}

function AssistantBubble({
  message,
}: {
  message: ChatMessage & { role: "assistant"; response: ManagerAssistantResponse };
}) {
  const { response } = message;
  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border-subtle bg-surface-raised text-gold-primary">
        <BotMessageSquare className="h-3.5 w-3.5" strokeWidth={1.8} />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        <div
          className={cn(
            "rounded-lg border px-4 py-3 text-[13px] leading-5",
            response.cannot_answer
              ? "border-border-subtle bg-surface-raised text-ink-secondary"
              : "border-border-subtle bg-surface text-ink-body"
          )}
        >
          <div className="whitespace-pre-wrap break-words">{response.answer}</div>
          {response.query_key && !response.cannot_answer && (
            <div className="mt-1.5 font-mono text-[10px] uppercase text-ink-quaternary">
              Query: {response.query_key.replace(/_/g, " ")}
            </div>
          )}
        </div>
        {response.chart_type === "number" && (
          <NumberChart data={response.chart_data} />
        )}
        {response.chart_type === "bar" && (
          <BarChart data={response.chart_data} />
        )}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-2 text-[12px] text-ink-tertiary">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border-subtle bg-surface-raised text-gold-primary">
        <BotMessageSquare className="h-3.5 w-3.5" strokeWidth={1.8} />
      </div>
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gold-primary [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gold-primary [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gold-primary [animation-delay:300ms]" />
      </span>
    </div>
  );
}

// ── Chart components ──────────────────────────────────────────────────────────

function NumberChart({ data }: { data: ManagerAssistantChartData }) {
  const value = data.value ?? 0;
  const unit = data.unit ?? "";
  const label = data.label ?? "";
  return (
    <div className="inline-flex items-center gap-3 rounded-lg border border-border-subtle bg-surface px-4 py-3">
      <Hash className="h-4 w-4 shrink-0 text-gold-primary" strokeWidth={1.8} />
      <div>
        <div className="text-[22px] font-semibold tabular-nums text-ink-primary">
          {typeof value === "number" && value % 1 !== 0
            ? value.toFixed(1)
            : value}
          {unit && <span className="ml-1 text-[13px] font-normal text-ink-tertiary">{unit}</span>}
        </div>
        {label && <div className="text-[11px] text-ink-tertiary">{label}</div>}
      </div>
    </div>
  );
}

function BarChart({ data }: { data: ManagerAssistantChartData }) {
  const labels = data.labels ?? [];
  const values = data.values ?? [];
  const unit = data.unit ?? "";
  if (!labels.length || !values.length) return null;
  const max = Math.max(...values, 1);
  return (
    <div className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="flex items-end gap-2">
        {BarChart2 && <BarChart2 className="mb-1 h-4 w-4 shrink-0 text-gold-primary" strokeWidth={1.8} />}
        <div className="min-w-0 flex-1 space-y-2">
          {labels.map((label, i) => {
            const val = values[i] ?? 0;
            const pct = Math.round((val / max) * 100);
            return (
              <div key={label} className="flex items-center gap-3 text-[12px]">
                <div className="w-28 shrink-0 truncate text-ink-tertiary" title={label}>
                  {label}
                </div>
                <div className="min-w-0 flex-1">
                  <div
                    className="h-5 rounded bg-gold-primary/70"
                    style={{ width: `${pct}%`, minWidth: "4px" }}
                  />
                </div>
                <div className="w-16 shrink-0 text-right font-mono text-ink-secondary">
                  {val}
                  {unit && <span className="ml-0.5 text-[10px] text-ink-quaternary">{unit}</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
