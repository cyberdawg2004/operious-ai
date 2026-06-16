"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Eye,
  FileText,
  History,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DonutChart } from "@/components/ui/chart";
import { CodeAsReadableText, DownloadableLog } from "@/components/ui/readable-data";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { TechnicalDetails } from "@/components/technical-details";
import {
  ApiError,
  createKnowledgeDocument,
  formatApiError,
  ingestKnowledgeDocument,
  listKnowledgeDocuments,
  listKnowledgeVersions,
  updateKnowledgeDocument,
  uploadKnowledgeDocument,
  type KnowledgeDocumentVersion,
  type TenantKnowledgeDocument,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PendingIntegrationState,
} from "@/components/data-state";

const PAGE_SIZE = 25;

const documentTypes: {
  id: "all" | TenantKnowledgeDocument["document_type"];
  label: string;
}[] = [
  { id: "all", label: "All documents" },
  { id: "sop", label: "SOPs" },
  { id: "policy", label: "Policies" },
  { id: "product_guide", label: "Product guides" },
  { id: "faq", label: "FAQs" },
  { id: "escalation_matrix", label: "Escalation matrices" },
];

const statusMeta: Record<TenantKnowledgeDocument["status"], { label: string; tone: StatusTone; color: string }> = {
  active: { label: "Active", tone: "success", color: "var(--chart-green)" },
  pending_index: { label: "Pending index", tone: "warning", color: "var(--chart-amber)" },
  indexing: { label: "Indexing", tone: "info", color: "var(--chart-blue)" },
  index_failed: { label: "Index failed", tone: "danger", color: "var(--chart-red)" },
  archived: { label: "Archived", tone: "neutral", color: "var(--chart-purple)" },
};

const reviewStatusMeta: Record<TenantKnowledgeDocument["review_status"], { label: string; tone: StatusTone }> = {
  quarantined: { label: "Quarantined — not used by AI", tone: "warning" },
  approved: { label: "Approved for use", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
};

type ModalState =
  | { type: "none" }
  | { type: "create" }
  | { type: "upload" }
  | { type: "view"; document: TenantKnowledgeDocument }
  | { type: "edit"; document: TenantKnowledgeDocument }
  | {
      type: "versions";
      document: TenantKnowledgeDocument;
      versions: KnowledgeDocumentVersion[];
      error: string | null;
      isLoading: boolean;
    }
  | { type: "notice"; title: string; message: string }
  | { type: "pending"; message: string };

export function KnowledgeBase() {
  const [activeCategory, setActiveCategory] =
    useState<(typeof documentTypes)[number]["id"]>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>({ type: "none" });
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [busyDocumentId, setBusyDocumentId] = useState<string | null>(null);

  const loadDocuments = useCallback(
    () =>
      listKnowledgeDocuments({
        document_type: activeCategory === "all" ? undefined : activeCategory,
        limit: PAGE_SIZE,
        offset: (currentPage - 1) * PAGE_SIZE,
      }),
    [activeCategory, currentPage]
  );

  const { data, error, isLoading, reload } = useApiResource(loadDocuments);

  const documents = useMemo(() => data?.items ?? [], [data?.items]);
  const filteredDocs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return documents;
    return documents.filter((doc) =>
      [doc.title, doc.document_id, doc.document_type, doc.status, doc.uploaded_by]
        .some((value) => value.toLowerCase().includes(query))
    );
  }, [documents, searchQuery]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  const statusBreakdown = useMemo(() => {
    const counts: Record<TenantKnowledgeDocument["status"], number> = {
      active: 0,
      pending_index: 0,
      indexing: 0,
      index_failed: 0,
      archived: 0,
    };
    for (const doc of documents) {
      counts[doc.status] += 1;
    }
    return (Object.keys(counts) as TenantKnowledgeDocument["status"][])
      .filter((status) => counts[status] > 0)
      .map((status) => ({
        label: statusMeta[status].label,
        value: counts[status],
        color: statusMeta[status].color,
      }));
  }, [documents]);

  const indexedCount = useMemo(
    () => documents.filter((doc) => Boolean(doc.vector_indexed_at)).length,
    [documents]
  );

  const openVersions = async (document: TenantKnowledgeDocument) => {
    setModal({
      type: "versions",
      document,
      versions: [],
      error: null,
      isLoading: true,
    });
    try {
      const page = await listKnowledgeVersions(document.document_id);
      setModal({
        type: "versions",
        document,
        versions: page.items,
        error: null,
        isLoading: false,
      });
    } catch (caught: unknown) {
      setModal({
        type: "versions",
        document,
        versions: [],
        error: formatApiError(caught),
        isLoading: false,
      });
    }
  };

  const closeModal = () => {
    setModal({ type: "none" });
    setFormError(null);
    setIsSubmitting(false);
  };

  const handleCreateDocument = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError(null);
    const form = new FormData(event.currentTarget);
    try {
      await createKnowledgeDocument({
        title: String(form.get("title") || ""),
        content: String(form.get("content") || ""),
        document_type: String(form.get("document_type") || "sop") as TenantKnowledgeDocument["document_type"],
        status: "pending_index",
      });
      closeModal();
      reload();
    } catch (caught: unknown) {
      setFormError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  const handleUpdateDocument = async (
    event: React.FormEvent<HTMLFormElement>,
    document: TenantKnowledgeDocument
  ) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError(null);
    const form = new FormData(event.currentTarget);
    try {
      await updateKnowledgeDocument(document.document_id, {
        content: String(form.get("content") || ""),
        status: String(form.get("status") || document.status) as TenantKnowledgeDocument["status"],
      });
      closeModal();
      reload();
    } catch (caught: unknown) {
      setFormError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  const handleIngestDocument = async (document: TenantKnowledgeDocument) => {
    setBusyDocumentId(document.document_id);
    try {
      const result = await ingestKnowledgeDocument(document.document_id);
      setModal({
        type: "notice",
        title: "Knowledge indexed",
        message: `${result.chunk_count} chunks and ${result.vector_count} vectors written to ${result.vector_index_name}.`,
      });
      reload();
    } catch (caught: unknown) {
      setModal({
        type: "notice",
        title: "Knowledge ingest failed",
        message: formatApiError(caught),
      });
    } finally {
      setBusyDocumentId(null);
    }
  };

  const handleUploadDocument = async (
    file: File,
    title: string,
    documentType: string
  ) => {
    setIsSubmitting(true);
    setFormError(null);
    try {
      await uploadKnowledgeDocument(file, title, documentType);
      closeModal();
      setModal({
        type: "notice",
        title: "Document submitted for review",
        message:
          "Your document has been uploaded and is awaiting review. A compliance reviewer must approve it before it can be indexed and used by the AI. Once approved, it will be queued for indexing automatically.",
      });
      reload();
    } catch (caught: unknown) {
      setFormError(_uploadErrorMessage(caught));
      setIsSubmitting(false);
    }
  };

  const columns: DataTableColumn<TenantKnowledgeDocument>[] = [
    {
      key: "title",
      header: "Document",
      width: "min-w-[280px]",
      render: (doc) => (
        <div className="flex min-w-0 items-start gap-2">
          <FileText size={16} strokeWidth={1.8} className="mt-0.5 shrink-0 text-ink-tertiary" />
          <div className="min-w-0">
            <p className="truncate text-[13.5px] font-semibold text-ink-primary">{doc.title}</p>
            <p className="mt-0.5 truncate text-meta">Uploaded by {doc.uploaded_by}</p>
          </div>
        </div>
      ),
    },
    {
      key: "type",
      header: "Type",
      width: "w-[160px]",
      render: (doc) => <span className="text-[12.5px] text-ink-secondary">{formatDocumentType(doc.document_type)}</span>,
    },
    {
      key: "status",
      header: "Status",
      width: "w-[200px]",
      render: (doc) => {
        const meta = statusMeta[doc.status];
        const reviewMeta = reviewStatusMeta[doc.review_status];
        return (
          <div className="flex flex-col gap-1">
            <StatusBadge label={meta.label} tone={meta.tone} />
            {doc.review_status !== "approved" && (
              <StatusBadge label={reviewMeta.label} tone={reviewMeta.tone} />
            )}
          </div>
        );
      },
    },
    {
      key: "version",
      header: "Version",
      width: "w-[90px]",
      numeric: true,
      render: (doc) => <span className="tabular text-[12.5px] text-ink-secondary">v{doc.version}</span>,
    },
    {
      key: "updated",
      header: "Updated",
      width: "w-[140px]",
      render: (doc) => (
        <span className="tabular text-[12.5px] text-ink-secondary" title={doc.created_at}>
          {formatDate(doc.created_at)}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "w-[220px]",
      align: "right",
      render: (doc) => (
        <div className="flex items-center justify-end gap-2">
          <DocumentActionMenu
            onView={() => setModal({ type: "view", document: doc })}
            onEdit={() => setModal({ type: "edit", document: doc })}
            onHistory={() => void openVersions(doc)}
            onIngest={() => void handleIngestDocument(doc)}
            ingestBusy={busyDocumentId === doc.document_id}
            onDelete={() =>
              setModal({
                type: "pending",
                message:
                  "The backend exposes create, update, list, ingest, and version read operations for knowledge documents, but no delete endpoint is currently available.",
              })
            }
          />
          <button
            type="button"
            onClick={() =>
              setExpandedDocId((current) => (current === doc.document_id ? null : doc.document_id))
            }
            className="cc-btn cc-btn-ghost"
            aria-label={`Toggle technical details for ${doc.title}`}
            aria-expanded={expandedDocId === doc.document_id}
          >
            {expandedDocId === doc.document_id ? (
              <ChevronDown size={14} strokeWidth={1.8} />
            ) : (
              <ChevronRight size={14} strokeWidth={1.8} />
            )}
            Details
          </button>
        </div>
      ),
    },
  ];

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <p className="text-meta">Tenant-scoped source material and SOP intelligence</p>

        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <label className="flex flex-col gap-1">
            <span className="sr-only">Document type</span>
            <select
              value={activeCategory}
              onChange={(event) => {
                setActiveCategory(event.target.value as (typeof documentTypes)[number]["id"]);
                setCurrentPage(1);
              }}
              className="cc-select h-10 min-w-[180px]"
            >
              {documentTypes.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.label}
                </option>
              ))}
            </select>
          </label>

          <div className="relative w-full md:w-[280px]">
            <Search
              size={14}
              strokeWidth={1.8}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search documents..."
              className="cc-input h-10 pl-9"
            />
          </div>

          <button
            type="button"
            onClick={reload}
            className="cc-btn cc-btn-secondary h-10 w-10"
            aria-label="Refresh documents"
          >
            <RefreshCw size={14} strokeWidth={1.8} className={cn(isLoading && "animate-spin")} />
          </button>

          <button
            type="button"
            onClick={() => setModal({ type: "create" })}
            className="cc-btn cc-btn-primary h-10"
          >
            New document
          </button>

          <button
            type="button"
            onClick={() => setModal({ type: "upload" })}
            className="cc-btn cc-btn-secondary h-10"
          >
            <Upload size={14} strokeWidth={1.8} />
            Upload document
          </button>
        </div>
      </div>

      {isLoading && <div className="mt-8"><LoadingState label="Loading tenant knowledge..." /></div>}

      {error && !isLoading && (
        <div className="mt-8">
          <ErrorState title="Knowledge documents unavailable" message={error} onAction={reload} />
        </div>
      )}

      {data && !isLoading && !error && (
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Documents</CardTitle>
                  <CardDescription>{categoryLabel(activeCategory)}</CardDescription>
                </div>
              </CardHeader>
              <p className="heading-page tabular">{data.total}</p>
              <div className="mt-4 border-t border-border-subtle pt-3 text-meta">
                {indexedCount} of {documents.length} documents on this page are indexed for retrieval
              </div>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Status breakdown</CardTitle>
                  <CardDescription>Across documents on this page</CardDescription>
                </div>
              </CardHeader>
              {statusBreakdown.length === 0 ? (
                <p className="text-meta">No documents to summarize yet.</p>
              ) : (
                <DonutChart
                  data={statusBreakdown}
                  centerValue={String(documents.length)}
                  centerLabel="documents"
                />
              )}
            </Card>
          </div>

          <div className="cc-card mt-6 overflow-hidden">
            {filteredDocs.length === 0 ? (
              <div className="p-6">
                <EmptyState
                  title="No knowledge documents"
                  message="The tenant knowledge endpoint returned no documents for the selected filters."
                  actionLabel="Refresh"
                  onAction={reload}
                />
              </div>
            ) : (
              <DataTable
                columns={columns}
                rows={filteredDocs}
                rowKey={(doc) => doc.document_id}
                minWidth="880px"
                expandedRowId={expandedDocId}
                renderExpanded={(doc) => (
                  <div className="px-4 py-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <h4 className="heading-section text-[13px]">Technical details</h4>
                      <DownloadableLog
                        data={doc}
                        filename={`knowledge-document-${doc.document_id}.json`}
                        label="Download document record"
                      />
                    </div>
                    <CodeAsReadableText
                      data={{
                        document_id: doc.document_id,
                        document_type: doc.document_type,
                        status: doc.status,
                        review_status: doc.review_status,
                        version: doc.version,
                        uploaded_by: doc.uploaded_by,
                        vector_indexed_at: doc.vector_indexed_at,
                        created_at: doc.created_at,
                      }}
                    />
                  </div>
                )}
              />
            )}

            <div className="flex min-h-12 flex-col gap-3 border-t border-border-subtle px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-meta">
                Showing {filteredDocs.length} of {data.total} documents
              </span>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="cc-btn cc-btn-secondary h-9 w-9 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Previous page"
                >
                  <ChevronRight size={14} strokeWidth={1.8} className="rotate-180" />
                </button>

                <span className="tabular text-meta px-1">
                  {currentPage} / {totalPages}
                </span>

                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                  className="cc-btn cc-btn-secondary h-9 w-9 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Next page"
                >
                  <ChevronRight size={14} strokeWidth={1.8} />
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {modal.type !== "none" && (
        <Modal onClose={closeModal}>
          {modal.type === "pending" && (
            <PendingIntegrationState
              title="Pending integration"
              message={modal.message}
              actionLabel="Dismiss"
              onAction={closeModal}
            />
          )}
          {modal.type === "notice" && (
            <NoticeState title={modal.title} message={modal.message} onClose={closeModal} />
          )}
          {modal.type === "create" && (
            <DocumentForm
              title="New document"
              submitLabel="Create document"
              error={formError}
              isSubmitting={isSubmitting}
              onSubmit={handleCreateDocument}
            />
          )}
          {modal.type === "upload" && (
            <UploadForm
              error={formError}
              isSubmitting={isSubmitting}
              onSubmit={handleUploadDocument}
            />
          )}
          {modal.type === "view" && <DocumentDetail document={modal.document} />}
          {modal.type === "edit" && (
            <DocumentForm
              title={`Edit ${modal.document.title}`}
              submitLabel="Save changes"
              document={modal.document}
              error={formError}
              isSubmitting={isSubmitting}
              onSubmit={(event) => void handleUpdateDocument(event, modal.document)}
            />
          )}
          {modal.type === "versions" && (
            <VersionHistoryState modal={modal} onRetry={() => void openVersions(modal.document)} />
          )}
        </Modal>
      )}
    </main>
  );
}

function DocumentActionMenu({
  onView,
  onEdit,
  onHistory,
  onIngest,
  ingestBusy,
  onDelete,
}: {
  onView: () => void;
  onEdit: () => void;
  onHistory: () => void;
  onIngest: () => void;
  ingestBusy: boolean;
  onDelete: () => void;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="cc-btn cc-btn-ghost h-9 w-9"
        aria-label="Document actions"
      >
        <MoreHorizontal size={14} strokeWidth={1.8} />
      </button>
      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 top-full z-20 mt-1 w-48 overflow-hidden rounded-lg border border-border-subtle bg-surface shadow-elevated">
            <MenuAction icon={Eye} label="View" onClick={onView} close={() => setIsOpen(false)} />
            <MenuAction icon={Pencil} label="Edit" onClick={onEdit} close={() => setIsOpen(false)} />
            <MenuAction icon={History} label="Version history" onClick={onHistory} close={() => setIsOpen(false)} />
            <MenuAction
              icon={Upload}
              label={ingestBusy ? "Indexing..." : "Ingest"}
              onClick={onIngest}
              close={() => setIsOpen(false)}
            />
            <MenuAction icon={Trash2} label="Delete" onClick={onDelete} close={() => setIsOpen(false)} danger />
          </div>
        </>
      )}
    </div>
  );
}

function MenuAction({
  icon: Icon,
  label,
  onClick,
  close,
  danger = false,
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  close: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => {
        onClick();
        close();
      }}
      className={cn(
        "flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors hover:bg-surface-raised",
        danger ? "text-red-alert" : "text-ink-secondary"
      )}
    >
      <Icon size={14} strokeWidth={1.8} />
      {label}
    </button>
  );
}

function Modal({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 sm:p-6">
      <div className="max-h-[88dvh] w-full max-w-3xl overflow-y-auto rounded-xl border border-border-subtle bg-surface p-5 shadow-elevated sm:p-6">
        <div className="mb-4 flex justify-end">
          <button type="button" onClick={onClose} className="cc-btn cc-btn-ghost h-9 w-9" aria-label="Close modal">
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function DocumentForm({
  title,
  submitLabel,
  document,
  error,
  isSubmitting,
  onSubmit,
}: {
  title: string;
  submitLabel: string;
  document?: TenantKnowledgeDocument;
  error: string | null;
  isSubmitting: boolean;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h2 className="heading-section text-[18px]">{title}</h2>
      {error && (
        <div className="rounded-md border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
          {error}
        </div>
      )}
      <label className="block">
        <span className="mb-1 block text-meta">Title</span>
        <input
          name="title"
          defaultValue={document?.title ?? ""}
          disabled={Boolean(document)}
          required
          className="cc-input h-10 w-full disabled:opacity-60"
        />
      </label>
      <label className="block">
        <span className="mb-1 block text-meta">Document type</span>
        <select
          name="document_type"
          defaultValue={document?.document_type ?? "sop"}
          disabled={Boolean(document)}
          className="cc-select h-10 w-full disabled:opacity-60"
        >
          {documentTypes
            .filter((type) => type.id !== "all")
            .map((type) => (
              <option key={type.id} value={type.id}>
                {type.label}
              </option>
            ))}
        </select>
      </label>
      {document && (
        <label className="block">
          <span className="mb-1 block text-meta">Status</span>
          <select name="status" defaultValue={document.status} className="cc-select h-10 w-full">
            <option value="active">Active</option>
            <option value="pending_index">Pending index</option>
            <option value="indexing">Indexing</option>
            <option value="archived">Archived</option>
          </select>
        </label>
      )}
      <label className="block">
        <span className="mb-1 block text-meta">Content</span>
        <textarea
          name="content"
          defaultValue={document?.content ?? ""}
          required
          rows={10}
          className="cc-input w-full py-2 leading-relaxed"
        />
      </label>
      <button type="submit" disabled={isSubmitting} className="cc-btn cc-btn-primary">
        {isSubmitting ? "Submitting..." : submitLabel}
      </button>
    </form>
  );
}

function DocumentDetail({ document }: { document: TenantKnowledgeDocument }) {
  const meta = statusMeta[document.status];
  const reviewMeta = reviewStatusMeta[document.review_status];
  return (
    <div className="space-y-4">
      <div>
        <h2 className="heading-section text-[18px]">{document.title}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge label={meta.label} tone={meta.tone} />
          <StatusBadge label={reviewMeta.label} tone={reviewMeta.tone} />
          <span className="text-meta">{formatDocumentType(document.document_type)}</span>
          <span className="text-meta">v{document.version}</span>
          <span className="text-meta">Updated {formatDate(document.created_at)}</span>
        </div>
        {document.review_status === "quarantined" && (
          <p className="mt-2 text-[12px] text-amber-600">
            This document is quarantined and not used for AI grounding. Approve it via the Knowledge Uploads tab in Needs Your Attention.
          </p>
        )}
      </div>

      <div className="max-h-[360px] overflow-auto whitespace-pre-wrap rounded-md border border-border-subtle bg-surface-raised p-4 text-body leading-relaxed">
        {document.content}
      </div>

      <TechnicalDetails label="Show details" openLabel="Hide details">
        <CodeAsReadableText
          data={{
            document_id: document.document_id,
            uploaded_by: document.uploaded_by,
            vector_indexed_at: document.vector_indexed_at,
            created_at: document.created_at,
          }}
        />
        <DownloadableLog
          data={document}
          filename={`knowledge-document-${document.document_id}.json`}
          label="Download document record"
          className="mt-3"
        />
      </TechnicalDetails>
    </div>
  );
}

function VersionHistoryState({
  modal,
  onRetry,
}: {
  modal: Extract<ModalState, { type: "versions" }>;
  onRetry: () => void;
}) {
  if (modal.isLoading) {
    return <LoadingState label="Loading document versions..." />;
  }
  if (modal.error) {
    return <ErrorState title="Version history unavailable" message={modal.error} onAction={onRetry} />;
  }
  return (
    <div className="space-y-4">
      <div>
        <h2 className="heading-section text-[18px]">Version history</h2>
        <p className="mt-1 text-meta">{modal.document.title}</p>
      </div>
      {modal.versions.length === 0 ? (
        <EmptyState
          title="No versions returned"
          message="The cognition version endpoint returned no historical versions for this document."
        />
      ) : (
        <div className="space-y-3">
          {modal.versions.map((version) => (
            <div key={version.version_id} className="rounded-md border border-border-subtle bg-surface-raised p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold text-ink-primary">v{version.version} &middot; {version.title}</span>
                <span className="tabular text-meta">{formatDate(version.created_at)}</span>
              </div>
              <p className="mt-2 line-clamp-3 text-body leading-relaxed">{version.content}</p>
              <TechnicalDetails label="Show details" openLabel="Hide details" className="mt-2">
                <CodeAsReadableText
                  data={{
                    version_id: version.version_id,
                    document_id: version.document_id,
                    status: version.status,
                    uploaded_by: version.uploaded_by,
                    source_approval_id: version.source_approval_id,
                    metadata: version.metadata,
                  }}
                />
                <DownloadableLog
                  data={version}
                  filename={`knowledge-document-${version.document_id}-v${version.version}.json`}
                  label="Download version record"
                  className="mt-3"
                />
              </TechnicalDetails>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NoticeState({ title, message, onClose }: { title: string; message: string; onClose: () => void }) {
  return (
    <div className="space-y-4">
      <h2 className="heading-section text-[18px]">{title}</h2>
      <p className="text-body leading-relaxed">{message}</p>
      <button type="button" onClick={onClose} className="cc-btn cc-btn-primary">
        Close
      </button>
    </div>
  );
}

function categoryLabel(category: (typeof documentTypes)[number]["id"]): string {
  return documentTypes.find((type) => type.id === category)?.label ?? "All documents";
}

function formatDocumentType(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(date);
}

function _uploadErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    switch (caught.message) {
      case "knowledge_upload_too_large":
        return "File is too large. Please upload a file under 15 MB.";
      case "knowledge_upload_type_rejected":
        return "File type not supported. Accepted formats: PDF, DOCX, plain text (.txt), and Markdown (.md). Executables and unrecognised binary files are always rejected.";
      case "knowledge_upload_unparsable":
        return "Could not extract text from this file. It may be a scanned image with no text layer, or the file may be corrupted. Try a different file or format.";
      case "knowledge_upload_invalid_document_type":
        return "Invalid document type selected. Please choose one from the list.";
    }
  }
  return formatApiError(caught);
}

const ACCEPTED_MIME =
  ".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown";

function UploadForm({
  error,
  isSubmitting,
  onSubmit,
}: {
  error: string | null;
  isSubmitting: boolean;
  onSubmit: (file: File, title: string, documentType: string) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const title = String(form.get("title") || "").trim();
    const documentType = String(form.get("document_type") || "sop");
    if (!selectedFile) return;
    onSubmit(selectedFile, title, documentType);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <h2 className="heading-section text-[18px]">Upload document</h2>
        <p className="mt-1 text-meta">
          Uploaded documents are quarantined until a reviewer approves them. They cannot be used by
          the AI until approved and indexed.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
          {error}
        </div>
      )}

      <div>
        <span className="mb-1 block text-meta">File</span>
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED_MIME}
          className="sr-only"
          onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
        />
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="cc-btn cc-btn-secondary h-10 shrink-0"
          >
            Choose file
          </button>
          <span className="truncate text-[13px] text-ink-secondary">
            {selectedFile ? selectedFile.name : "No file chosen"}
          </span>
        </div>
        <p className="mt-1 text-meta">Accepted: PDF, DOCX, TXT, Markdown — up to 15 MB</p>
      </div>

      <label className="block">
        <span className="mb-1 block text-meta">Title</span>
        <input
          name="title"
          required
          placeholder="e.g. Refund Policy v3"
          className="cc-input h-10 w-full"
        />
      </label>

      <label className="block">
        <span className="mb-1 block text-meta">Document type</span>
        <select name="document_type" defaultValue="sop" className="cc-select h-10 w-full">
          {documentTypes
            .filter((type) => type.id !== "all")
            .map((type) => (
              <option key={type.id} value={type.id}>
                {type.label}
              </option>
            ))}
        </select>
      </label>

      <button
        type="submit"
        disabled={isSubmitting || !selectedFile}
        className="cc-btn cc-btn-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSubmitting ? "Uploading..." : "Upload document"}
      </button>
    </form>
  );
}
