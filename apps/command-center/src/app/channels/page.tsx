'use client';

import { useState } from 'react';
import { Plus, RefreshCw, Radio } from 'lucide-react';
import {
  useCreateChannel,
  useTenantChannels,
  useVerifyChannel,
} from '@operious/sdk';
import type {
  TenantChannelConfigurationDto,
  TenantChannelStatus,
  TenantChannelType,
} from '@operious/types';
import { toast } from 'sonner';
import { PageHeader } from '@/components/layout/page-header';
import { StatusPill } from '@/components/ui/status-pill';
import { ChannelIcon, channelLabel } from '@/components/ui/channel-icon';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { useRightPanel } from '@/components/layout/right-panel';
import { cn } from '@/lib/cn';

const STATUS_TONE: Record<
  TenantChannelStatus,
  'active' | 'pending' | 'denied' | 'neutral'
> = {
  active: 'active',
  pending_verification: 'pending',
  error: 'denied',
  paused: 'neutral',
};

const CHANNEL_OPTIONS: readonly TenantChannelType[] = [
  'email',
  'whatsapp',
  'lark',
  'sms',
  'web_form',
  'api',
];

export default function ChannelsPage() {
  const query = useTenantChannels();
  const verify = useVerifyChannel();
  const [adding, setAdding] = useState(false);
  const { open } = useRightPanel();

  const handleConfigure = (channel: TenantChannelConfigurationDto) => {
    open({
      key: channel.configId as unknown as string,
      title: channelLabel(channel.channelType),
      subtitle: channel.routingAddress,
      body: <ChannelDetail channel={channel} />,
    });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Boundary', 'Channels']}
        title="Channel Configuration"
        actions={
          <button
            type="button"
            onClick={() => setAdding(true)}
            className={cn(
              'flex h-8 items-center gap-1.5 rounded-sm border border-accent bg-accent/15 px-3',
              'font-mono text-2xs uppercase tracking-wider text-accent',
              'transition-colors hover:bg-accent/25',
            )}
          >
            <Plus className="h-3.5 w-3.5" />
            Add Channel
          </button>
        }
      />

      {query.isLoading ? (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44" rounded="md" />
          ))}
        </div>
      ) : query.isError ? (
        <div className="rounded-md border border-signal-deny/30 bg-signal-deny/5 p-6">
          <StatusPill tone="failed">backend error</StatusPill>
          <p className="mt-2 font-mono text-2xs text-signal-deny">
            {query.error?.message}
          </p>
        </div>
      ) : (query.data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={Radio}
          title="No channels configured for this tenant."
          description="Add Email, WhatsApp, Lark, SMS, Web Form, or API channels to route inbound traffic into the operational substrate."
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {query.data!.items.map((channel) => (
            <article
              key={channel.configId as unknown as string}
              className={cn(
                'flex flex-col gap-3 rounded-md border border-line bg-bg-inset p-4 shadow-card',
                'transition-shadow duration-150 hover:shadow-raised',
              )}
            >
              <header className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-sm bg-bg text-fg">
                    <ChannelIcon kind={channel.channelType} />
                  </span>
                  <div>
                    <p className="font-display text-base text-fg">
                      {channelLabel(channel.channelType)}
                    </p>
                    <p className="font-mono text-2xs text-fg-subtle">
                      {channel.routingAddress}
                    </p>
                  </div>
                </div>
                <StatusPill tone={STATUS_TONE[channel.status]}>
                  {channel.status.replace(/_/g, ' ')}
                </StatusPill>
              </header>
              <dl className="space-y-1 font-mono text-2xs">
                <Row label="Last verified" value={channel.verifiedAt ?? '\u2014'} />
                <Row label="Inbound (24h)" value="\u2014" />
                <Row
                  label="Credentials"
                  value={
                    <span className="text-fg-dim">\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (write-only)</span>
                  }
                />
              </dl>
              <div className="flex items-center justify-end gap-2 border-t border-line pt-3">
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await verify.mutateAsync({ configId: channel.configId });
                      toast.success('Verification handshake initiated', {
                        description:
                          'Backend dispatches a test webhook and validates the signature.',
                      });
                    } catch (cause) {
                      toast.error('Verification declined', {
                        description:
                          cause instanceof Error
                            ? cause.message
                            : 'transport error',
                      });
                    }
                  }}
                  disabled={verify.isPending}
                  className={cn(
                    'flex items-center gap-1.5 rounded-sm border border-line bg-bg px-2.5 py-1',
                    'font-mono text-2xs uppercase tracking-wider text-fg-muted',
                    'transition-colors hover:border-line-strong hover:text-fg',
                    verify.isPending && 'opacity-50',
                  )}
                >
                  <RefreshCw className="h-3 w-3" />
                  Verify
                </button>
                <button
                  type="button"
                  onClick={() => handleConfigure(channel)}
                  className={cn(
                    'rounded-sm border border-accent bg-accent/15 px-2.5 py-1',
                    'font-mono text-2xs uppercase tracking-wider text-accent',
                    'transition-colors hover:bg-accent/25',
                  )}
                >
                  Configure
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {adding ? (
        <AddChannelModal
          onClose={() => setAdding(false)}
          onCreated={() => {
            setAdding(false);
            void query.refetch();
          }}
        />
      ) : null}
    </div>
  );
}

const Row = ({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) => (
  <div className="flex items-center justify-between">
    <dt className="text-fg-dim">{label}</dt>
    <dd className="text-fg-muted">{value}</dd>
  </div>
);

const ChannelDetail = ({
  channel,
}: {
  channel: TenantChannelConfigurationDto;
}) => (
  <div className="space-y-4">
    <div className="grid grid-cols-2 gap-2 text-mono text-fg-subtle">
      <span>type \u00b7 {channel.channelType}</span>
      <span>status \u00b7 {channel.status}</span>
      <span className="col-span-2 break-all">
        routing \u00b7 {channel.routingAddress}
      </span>
    </div>
    <section>
      <p className="mb-2 text-mono text-fg-dim">credentials</p>
      <p className="rounded-sm border border-line bg-bg p-3 font-mono text-2xs text-fg-dim">
        write-only \u2014 once saved, credentials are encrypted at rest and never
        returned to the browser. Re-enter via the Update endpoint to rotate.
      </p>
    </section>
    <p className="text-2xs text-fg-subtle">
      Configuration changes flow through the tenant configuration service.
      Audit log captures every credential rotation and verification handshake.
    </p>
  </div>
);

interface AddChannelModalProps {
  readonly onClose: () => void;
  readonly onCreated: () => void;
}

const STEPS = ['Type', 'Routing', 'Credentials', 'Verify', 'Activate'] as const;
type Step = (typeof STEPS)[number];

const AddChannelModal = ({ onClose, onCreated }: AddChannelModalProps) => {
  const [step, setStep] = useState<Step>('Type');
  const [channelType, setChannelType] = useState<TenantChannelType>('email');
  const [routingAddress, setRoutingAddress] = useState('');
  const [credentials, setCredentials] = useState('{}');
  const [webhookSecret, setWebhookSecret] = useState('');
  const create = useCreateChannel();

  const next = () => {
    const idx = STEPS.indexOf(step);
    const target = STEPS[idx + 1];
    if (target) setStep(target);
  };
  const prev = () => {
    const idx = STEPS.indexOf(step);
    const target = STEPS[idx - 1];
    if (target) setStep(target);
  };

  const submit = async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(credentials);
    } catch {
      toast.error('Credentials must be valid JSON');
      return;
    }
    try {
      await create.mutateAsync({
        channelType,
        routingAddress,
        credentials: parsed,
        webhookSecret,
      });
      toast.success('Channel created', {
        description:
          'Awaiting verification handshake. Run Verify to dispatch a test webhook.',
      });
      onCreated();
    } catch (cause) {
      toast.error('Backend declined', {
        description: cause instanceof Error ? cause.message : 'transport error',
      });
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-fg/[0.08] animate-fade-in"
      />
      <div
        role="dialog"
        aria-modal
        className={cn(
          'relative w-full max-w-lg rounded-lg border border-line bg-bg-inset shadow-panel',
          'animate-scale-in',
        )}
      >
        <header className="flex items-center justify-between border-b border-line px-5 py-3">
          <div>
            <p className="text-mono text-fg-dim">add channel</p>
            <h2 className="font-display text-lg text-fg">{step}</h2>
          </div>
          <ol className="flex items-center gap-1.5 text-mono text-fg-dim">
            {STEPS.map((s, i) => (
              <li
                key={s}
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full border',
                  STEPS.indexOf(step) >= i
                    ? 'border-accent text-accent'
                    : 'border-line text-fg-dim',
                )}
              >
                {i + 1}
              </li>
            ))}
          </ol>
        </header>
        <div className="space-y-3 px-5 py-4">
          {step === 'Type' ? (
            <div className="grid grid-cols-2 gap-2">
              {CHANNEL_OPTIONS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setChannelType(option)}
                  className={cn(
                    'flex items-center gap-2 rounded-sm border px-3 py-2 text-left',
                    'transition-colors',
                    channelType === option
                      ? 'border-accent bg-accent/10 text-fg'
                      : 'border-line bg-bg text-fg-muted hover:border-line-strong hover:text-fg',
                  )}
                >
                  <ChannelIcon kind={option} />
                  {channelLabel(option)}
                </button>
              ))}
            </div>
          ) : null}

          {step === 'Routing' ? (
            <label className="block">
              <span className="text-mono text-fg-dim">routing address</span>
              <input
                value={routingAddress}
                onChange={(event) => setRoutingAddress(event.target.value)}
                placeholder="ops@example.com or +1\u2026 or webhook URL"
                className={cn(
                  'mt-1 w-full rounded-sm border border-line bg-bg px-3 py-2',
                  'font-mono text-2xs text-fg placeholder:text-fg-dim',
                  'focus:border-accent focus:outline-none',
                )}
              />
            </label>
          ) : null}

          {step === 'Credentials' ? (
            <>
              <label className="block">
                <span className="text-mono text-fg-dim">credentials (JSON)</span>
                <textarea
                  value={credentials}
                  onChange={(event) => setCredentials(event.target.value)}
                  rows={6}
                  className={cn(
                    'mt-1 w-full rounded-sm border border-line bg-bg px-3 py-2',
                    'font-mono text-2xs text-fg outline-none focus:border-accent',
                  )}
                />
              </label>
              <label className="block">
                <span className="text-mono text-fg-dim">webhook secret</span>
                <input
                  type="password"
                  value={webhookSecret}
                  onChange={(event) => setWebhookSecret(event.target.value)}
                  className={cn(
                    'mt-1 w-full rounded-sm border border-line bg-bg px-3 py-2',
                    'font-mono text-2xs text-fg outline-none focus:border-accent',
                  )}
                />
              </label>
              <p className="text-2xs text-fg-subtle">
                Credentials are encrypted on save and never returned. To rotate,
                re-enter them \u2014 the backend will replace the encrypted blob.
              </p>
            </>
          ) : null}

          {step === 'Verify' ? (
            <p className="text-sm text-fg-muted">
              Submitting will dispatch a verification handshake from the
              backend. The handshake test-pings the channel and verifies the
              signature before admitting traffic.
            </p>
          ) : null}

          {step === 'Activate' ? (
            <p className="text-sm text-fg-muted">
              Once activated the channel begins routing inbound traffic into
              the operational substrate, subject to tenant governance policies.
            </p>
          ) : null}
        </div>
        <footer className="flex items-center justify-between border-t border-line bg-bg-raised px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="font-mono text-2xs uppercase tracking-wider text-fg-subtle hover:text-fg"
          >
            Cancel
          </button>
          <div className="flex items-center gap-2">
            {step !== 'Type' ? (
              <button
                type="button"
                onClick={prev}
                className="rounded-sm border border-line bg-bg-inset px-3 py-1.5 font-mono text-2xs uppercase tracking-wider text-fg-muted hover:text-fg"
              >
                Back
              </button>
            ) : null}
            {step !== 'Activate' ? (
              <button
                type="button"
                onClick={next}
                className="rounded-sm border border-accent bg-accent/15 px-3 py-1.5 font-mono text-2xs uppercase tracking-wider text-accent hover:bg-accent/25"
              >
                Next
              </button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={create.isPending}
                className="rounded-sm border border-accent bg-accent/15 px-3 py-1.5 font-mono text-2xs uppercase tracking-wider text-accent hover:bg-accent/25 disabled:opacity-50"
              >
                {create.isPending ? 'Submitting\u2026' : 'Activate'}
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
};
