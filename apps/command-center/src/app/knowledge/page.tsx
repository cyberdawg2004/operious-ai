'use client';

import { useMemo, useState } from 'react';
import { Search, Upload, FileText } from 'lucide-react';
import {
  useTenantKnowledge,
  useUpdateKnowledgeDocument,
} from '@operious/sdk';
import type {
  TenantKnowledgeDocumentDto,
  TenantKnowledgeDocumentStatus,
  TenantKnowledgeDocumentType,
} from '@operious/types';
import { toast } from 'sonner';
import { PageHeader } from '@/components/layout/page-header';
import { StatusPill } from '@/components/ui/status-pill';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { useRightPanel } from '@/components/layout/right-panel';
import { cn } from '@/lib/cn';

type Category =
  | 'all'
  | 'sop'
  | 'policy'
  | 'product_guide'
  | 'faq'
  | 'escalation_matrix'
  | 'archived';

const CATEGORIES: readonly { value: Category; label: string }[] = [
  { value: 'all', label: 'All Documents' },
  { value: 'sop', label: 'SOPs' },
  { value: 'policy', label: 'Policies' },
  { value: 'product_guide', label: 'Product Guides' },
  { value: 'faq', label: 'FAQs' },
  { value: 'escalation_matrix', label: 'Escalation Matrices' },
  { value: 'archived', label: 'Archived' },
];

const STATUS_TONE: Record<
  TenantKnowledgeDocumentStatus,
  'active' | 'pending' | 'denied' | 'neutral'
> = {
  active: 'active',
  indexing: 'pending',
  pending_index: 'pending',
  failed: 'denied',
  archived: 'neutral',
};

export default function KnowledgeBasePage() {
  const [category, setCategory] = useState<Category>('all');
  const [search, setSearch] = useState('');
  const query = useTenantKnowledge(
    category === 'all'
      ? {}
      : category === 'archived'
        ? { status: 'archived' as TenantKnowledgeDocumentStatus }
        : { documentType: category as TenantKnowledgeDocumentType },
  );
  const { open } = useRightPanel();

  const rows = useMemo(() => {
    const items = query.data?.items ?? [];
    const needle = search.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((doc) =>
      doc.title.toLowerCase().includes(needle),
    );
  }, [query.data, search]);

  const handleSelect = (doc: TenantKnowledgeDocumentDto) => {
    open({
      key: doc.documentId as unknown as string,
      title: doc.title,
      subtitle: `${doc.documentType.replace(/_/g, ' ')} \u00b7 v${doc.version}`,
      body: <DocumentEditor doc={doc} onSaved={() => void query.refetch()} />,
    });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Knowledge', 'Base']}
        title="Knowledge Base"
        actions={
          <>
            <label className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-dim" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search documents\u2026"
                className={cn(
                  'h-8 w-64 rounded-sm border border-line bg-bg-inset pl-8 pr-3',
                  'font-mono text-2xs text-fg placeholder:text-fg-dim',
                  'focus:border-accent focus:outline-none',
                )}
              />
            </label>
            <button
              type="button"
              onClick={() =>
                toast.info('Upload', {
                  description:
                    'Document upload is wired in the Knowledge Editor right panel \u2014 select an existing document to edit, or use the create endpoint via the SDK.',
                })
              }
              className={cn(
                'flex h-8 items-center gap-1.5 rounded-sm border border-accent bg-accent/15 px-3',
                'font-mono text-2xs uppercase tracking-wider text-accent',
                'transition-colors hover:bg-accent/25',
              )}
            >
              <Upload className="h-3.5 w-3.5" />
              Upload Document
            </button>
          </>
        }
      />

      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
        <nav
          aria-label="Categories"
          className="space-y-0.5 rounded-md border border-line bg-bg-inset p-2"
        >
          {CATEGORIES.map((cat) => {
            const active = category === cat.value;
            return (
              <button
                key={cat.value}
                type="button"
                onClick={() => setCategory(cat.value)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-left',
                  'font-sans text-sm transition-colors',
                  active
                    ? 'bg-bg text-fg shadow-card'
                    : 'text-fg-subtle hover:bg-bg hover:text-fg',
                )}
              >
                <FileText
                  className={cn(
                    'h-3.5 w-3.5 shrink-0',
                    active ? 'text-accent' : 'text-fg-dim',
                  )}
                />
                {cat.label}
              </button>
            );
          })}
        </nav>

        <section className="rounded-md border border-line bg-bg-inset shadow-card">
          {query.isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10" rounded="sm" />
              ))}
            </div>
          ) : query.isError ? (
            <div className="p-6">
              <StatusPill tone="failed">backend error</StatusPill>
              <p className="mt-2 font-mono text-2xs text-signal-deny">
                {query.error?.message}
              </p>
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              title="No documents in this category."
              description="Upload SOPs, policies, product guides, FAQs, and escalation matrices to power tenant-scoped grounding."
              className="border-0"
            />
          ) : (
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-line bg-bg-raised">
                  <Th>Title</Th>
                  <Th>Type</Th>
                  <Th>Version</Th>
                  <Th>Status</Th>
                  <Th>Indexed</Th>
                  <Th>Last updated</Th>
                  <Th>Author</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((doc) => (
                  <tr
                    key={doc.documentId as unknown as string}
                    role="button"
                    tabIndex={0}
                    onClick={() => handleSelect(doc)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        handleSelect(doc);
                      }
                    }}
                    className="cursor-pointer border-b border-line/80 transition-colors hover:bg-bg-raised"
                  >
                    <td className="px-3 py-2 text-fg">{doc.title}</td>
                    <td className="px-3 py-2 font-mono text-2xs text-fg-muted">
                      {doc.documentType.replace(/_/g, ' ')}
                    </td>
                    <td className="px-3 py-2 font-mono text-2xs text-fg-muted">
                      v{doc.version}
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill tone={STATUS_TONE[doc.status]}>
                        {doc.status.replace(/_/g, ' ')}
                      </StatusPill>
                    </td>
                    <td className="px-3 py-2 font-mono text-2xs text-fg-subtle">
                      {doc.vectorIndexedAt ?? '\u2014'}
                    </td>
                    <td className="px-3 py-2 font-mono text-2xs text-fg-subtle">
                      {doc.createdAt}
                    </td>
                    <td className="px-3 py-2 font-mono text-2xs text-fg-subtle">
                      {doc.uploadedBy}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}

const Th = ({ children }: { children: React.ReactNode }) => (
  <th
    scope="col"
    className="px-3 py-2 text-left font-mono text-2xs uppercase tracking-wider text-fg-dim"
  >
    {children}
  </th>
);

const DocumentEditor = ({
  doc,
  onSaved,
}: {
  doc: TenantKnowledgeDocumentDto;
  onSaved: () => void;
}) => {
  const [content, setContent] = useState(doc.content);
  const update = useUpdateKnowledgeDocument();
  const save = async () => {
    try {
      await update.mutateAsync({
        documentId: doc.documentId,
        content,
      });
      toast.success('Document saved', {
        description:
          'Backend will reindex this document and bump the version on confirmation.',
      });
      onSaved();
    } catch (cause) {
      toast.error('Save declined', {
        description: cause instanceof Error ? cause.message : 'transport error',
      });
    }
  };
  const archive = async () => {
    try {
      await update.mutateAsync({
        documentId: doc.documentId,
        status: 'archived' as TenantKnowledgeDocumentStatus,
      });
      toast.success('Document archived');
      onSaved();
    } catch (cause) {
      toast.error('Archive declined', {
        description: cause instanceof Error ? cause.message : 'transport error',
      });
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 text-mono text-fg-subtle">
        <span>Type \u00b7 {doc.documentType.replace(/_/g, ' ')}</span>
        <span>Version \u00b7 v{doc.version}</span>
        <span>Status \u00b7 {doc.status.replace(/_/g, ' ')}</span>
        <span>Author \u00b7 {doc.uploadedBy}</span>
      </div>

      <label className="block">
        <span className="text-mono text-fg-dim">content (markdown)</span>
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={18}
          className={cn(
            'mt-1 w-full rounded-sm border border-line bg-bg-inset px-3 py-2',
            'font-mono text-2xs text-fg placeholder:text-fg-dim',
            'focus:border-accent focus:outline-none',
          )}
        />
      </label>

      <section>
        <p className="mb-2 text-mono text-fg-dim">version history</p>
        <p className="rounded-sm border border-line bg-bg p-3 text-mono text-fg-subtle">
          version log streams from the backend; rollback writes a new version
          rather than mutating the historical record.
        </p>
      </section>

      <div className="flex items-center justify-end gap-2 border-t border-line pt-3">
        <button
          type="button"
          onClick={archive}
          disabled={update.isPending}
          className={cn(
            'rounded-sm border border-line bg-bg-inset px-3 py-1.5',
            'font-mono text-2xs uppercase tracking-wider text-fg-muted',
            'transition-colors hover:border-signal-deny hover:text-signal-deny',
            update.isPending && 'opacity-50',
          )}
        >
          Archive
        </button>
        <button
          type="button"
          onClick={save}
          disabled={update.isPending}
          className={cn(
            'rounded-sm border border-accent bg-accent/15 px-3 py-1.5',
            'font-mono text-2xs uppercase tracking-wider text-accent',
            'transition-colors hover:bg-accent/25',
            update.isPending && 'opacity-50',
          )}
        >
          {update.isPending ? 'Saving\u2026' : 'Save'}
        </button>
      </div>
    </div>
  );
};
