'use client';

import { useId, useRef, useState, useTransition } from 'react';
import { askSubstrate, type AskMessage } from '../../app/actions/cognition';
import { KernelSeal } from '../brand/kernel-seal';

/**
 * SubstrateChat — embedded live cognition surface.
 *
 * Constitutional design:
 *   - The marketing site never imports the operational SDK or contracts.
 *   - The client never touches fetch directly. All transport happens via
 *     the `askSubstrate` server action, which proxies to the configured
 *     cognition runtime.
 *   - The conversation_id is generated client-side per session so the
 *     runtime can correlate turns within one visitor's exchange.
 *   - The UI degrades gracefully if the runtime is unavailable.
 */
interface Message extends AskMessage {
  readonly id: string;
  readonly status?: 'pending' | 'unavailable' | 'error';
}

interface Props {
  readonly variant?: 'inset' | 'floating';
  readonly suggestions?: ReadonlyArray<string>;
  readonly className?: string;
  readonly headerLabel?: string;
}

const DEFAULT_SUGGESTIONS = [
  'How does fail-closed governance work?',
  'Show me a forensic trace example',
  'What does tenant isolation prevent?',
  'How are SOPs versioned?',
] as const;

const newId = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `m_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

export const SubstrateChat = ({
  variant = 'inset',
  suggestions = DEFAULT_SUGGESTIONS,
  className,
  headerLabel = 'Operious Substrate · Live',
}: Props) => {
  const conversationId = useRef<string>(`mkt_${newId()}`);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'seed',
      role: 'assistant',
      content:
        'I am the Operious substrate cognition runtime. I am bounded by Operious documentation and the same governance policies that bind every operational deployment. Ask me anything about the architecture, governance doctrine, or operational guarantees.',
    },
  ]);
  const [input, setInput] = useState('');
  const [pending, startTransition] = useTransition();
  const inputId = useId();
  const threadRef = useRef<HTMLDivElement | null>(null);

  const submit = (raw: string) => {
    const message = raw.trim();
    if (!message || pending) return;

    const userMsg: Message = { id: newId(), role: 'user', content: message };
    const placeholder: Message = {
      id: `${userMsg.id}_a`,
      role: 'assistant',
      content: '',
      status: 'pending',
    };

    setMessages((prev) => [...prev, userMsg, placeholder]);
    setInput('');

    startTransition(async () => {
      const history: AskMessage[] = messages.map(({ role, content }) => ({ role, content }));
      const result = await askSubstrate(conversationId.current, history, message);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === placeholder.id
            ? {
                ...m,
                content: result.reply,
                status:
                  result.status === 'unavailable'
                    ? 'unavailable'
                    : result.status === 'error'
                      ? 'error'
                      : undefined,
              }
            : m,
        ),
      );
      window.requestAnimationFrame(() => {
        threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
      });
    });
  };

  const onFormSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submit(input);
  };

  const isFloating = variant === 'floating';
  const wrapperBase = isFloating
    ? 'flex h-full flex-col'
    : 'flex flex-col';
  const panelHeight = isFloating ? 'h-full' : 'h-[500px]';

  return (
    <div
      className={[
        'rounded-lg border border-dark-line bg-dark-canvas text-dark-ink shadow-modal overflow-hidden',
        wrapperBase,
        className ?? '',
      ].join(' ')}
    >
      <div className="flex items-center justify-between border-b border-dark-line bg-dark-surface/70 px-5 py-3.5">
        <div className="flex items-center gap-3">
          <KernelSeal size={22} variant="dark" animated={false} />
          <span className="label-mono text-dark-ink">{headerLabel}</span>
        </div>
        <span className="flex items-center gap-2 label-mono text-success">
          <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-success" />
          live
        </span>
      </div>

      <div
        ref={threadRef}
        className={`flex-1 overflow-y-auto px-5 py-5 space-y-4 ${panelHeight}`}
      >
        {messages.map((m) => {
          const isUser = m.role === 'user';
          return (
            <div
              key={m.id}
              className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={[
                  'max-w-[85%] rounded-md px-4 py-3 text-sm leading-relaxed',
                  isUser
                    ? 'bg-gold/15 text-dark-ink border border-gold/30'
                    : 'bg-dark-surface text-dark-ink border border-dark-line',
                  m.status === 'unavailable' ? 'border-warning/40 text-warning' : '',
                  m.status === 'error' ? 'border-critical/40 text-critical' : '',
                ].join(' ')}
              >
                {m.status === 'pending' ? (
                  <span className="inline-flex items-center gap-2 text-dark-ink-muted">
                    <span className="label-mono">substrate</span>
                    <span className="inline-flex gap-0.5">
                      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-gold-highlight" />
                      <span
                        className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-gold-highlight"
                        style={{ animationDelay: '120ms' }}
                      />
                      <span
                        className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-gold-highlight"
                        style={{ animationDelay: '240ms' }}
                      />
                    </span>
                  </span>
                ) : (
                  m.content
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="border-t border-dark-line bg-dark-surface/60 px-5 py-4 space-y-3">
        {suggestions.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => submit(s)}
                disabled={pending}
                data-cursor="interactive"
                className="rounded-full border border-dark-line bg-dark-canvas px-3 py-1.5 eyebrow text-dark-ink-muted transition-colors hover:border-gold/50 hover:text-gold-highlight disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}

        <form onSubmit={onFormSubmit} className="flex items-center gap-2">
          <label htmlFor={inputId} className="sr-only">
            Ask the substrate
          </label>
          <input
            id={inputId}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={pending}
            placeholder="Ask anything about the substrate…"
            className="flex-1 rounded-md border border-dark-line bg-dark-canvas px-3.5 py-2.5 text-sm text-dark-ink placeholder:text-dark-ink-dim focus:border-gold/60 focus:outline-none disabled:opacity-60"
            autoComplete="off"
          />
          <button
            type="submit"
            disabled={pending || input.trim().length === 0}
            className="rounded-md bg-gold px-4 py-2.5 text-sm font-medium text-dark-canvas transition-colors hover:bg-gold-highlight disabled:opacity-40"
          >
            {pending ? '…' : 'Ask'}
          </button>
        </form>

        <p className="label-mono text-dark-ink-dim">
          Cognition Runtime · ToolInvoker-bounded
        </p>
      </div>
    </div>
  );
};

export default SubstrateChat;
