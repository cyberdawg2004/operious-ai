"use client";

import { useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Eye,
  FileText,
  Folder,
  History,
  MoreHorizontal,
  Pencil,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  createKnowledgeDocument,
  formatApiError,
  ingestKnowledgeDocument,
  listKnowledgeDocuments,
  listKnowledgeVersions,
  updateKnowledgeDocument,
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
  { id: "all", label: "All Documents" },
  { id: "sop", label: "SOPs" },
  { id: "policy", label: "Policies" },
  { id: "product_guide", label: "Product Guides" },
  { id: "faq", label: "FAQs" },
  { id: "escalation_matrix", label: "Escalation Matrices" },
];

type ModalState =
  | { type: "none" }
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
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
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

  const toggleDocSelection = (id: string) => {
    setSelectedDocs((prev) =>
      prev.includes(id) ? prev.filter((docId) => docId !== id) : [...prev, id]
    );
  };

  const toggleAllSelection = () => {
    if (selectedDocs.length === filteredDocs.length) {
      setSelectedDocs([]);
    } else {
      setSelectedDocs(filteredDocs.map((doc) => doc.document_id));
    }
  };

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

  return (
    <div className="flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-12 lg:py-8">
      <div className="mb-8">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary mb-2">
          Knowledge · Document Management
        </p>

        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <h1 className="font-serif text-[32px] font-bold text-ink-primary">
            Knowledge Base
          </h1>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative w-full sm:w-[280px]">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-tertiary"
                strokeWidth={1.5}
              />
              <input
                type="text"
                placeholder="Search documents..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-11 w-full rounded-lg border border-border-subtle bg-surface pl-9 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary transition-colors focus:outline-none focus:border-gold-primary sm:h-9"
              />
            </div>

            <button
              onClick={() => setModal({ type: "upload" })}
              className="flex h-11 items-center justify-center gap-2 rounded bg-gold-primary px-4 font-sans text-[13px] font-medium text-white transition-colors duration-160 hover:bg-gold-bright sm:h-9"
            >
              <Upload className="w-3.5 h-3.5" strokeWidth={1.5} />
              Upload Document
            </button>
          </div>
        </div>
      </div>

      {isLoading && <LoadingState label="Loading tenant knowledge..." />}

      {error && !isLoading && (
        <ErrorState
          title="Knowledge documents unavailable"
          message={error}
          onAction={reload}
        />
      )}

      {data && !isLoading && !error && (
        <div className="flex flex-col gap-4 xl:flex-row xl:gap-6">
          <div className="w-full flex-shrink-0 xl:w-60">
            <div className="bg-surface border border-border-subtle rounded-lg p-4">
              <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary mb-4">
                Categories
              </h2>

              <div className="space-y-1">
                {documentTypes.map((category) => (
                  <button
                    key={category.id}
                    onClick={() => {
                      setActiveCategory(category.id);
                      setCurrentPage(1);
                      setSelectedDocs([]);
                    }}
                    className={cn(
                      "flex h-11 w-full items-center gap-2 rounded px-3 transition-colors duration-160 sm:h-9",
                      activeCategory === category.id
                        ? "bg-[var(--gold-bg)] border-l-4 border-l-[var(--gold-primary)] -ml-px"
                        : "hover:bg-[var(--surface-sunken)]"
                    )}
                  >
                    <Folder
                      className={cn(
                        "w-3.5 h-3.5",
                        activeCategory === category.id
                          ? "text-ink-primary"
                          : "text-ink-tertiary"
                      )}
                      strokeWidth={1.5}
                    />
                    <span
                      className={cn(
                        "flex-1 text-left text-[13px] font-medium",
                        activeCategory === category.id
                          ? "text-ink-primary"
                          : "text-ink-secondary"
                      )}
                    >
                      {category.label}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-x-auto rounded-lg border border-border-subtle bg-surface">
            <div className="flex h-11 min-w-[920px] items-center border-b border-border-subtle bg-surface-raised px-4 sm:h-10">
              <div className="flex w-12 items-center justify-center sm:w-10">
                <input
                  type="checkbox"
                  checked={
                    selectedDocs.length === filteredDocs.length &&
                    filteredDocs.length > 0
                  }
                  onChange={toggleAllSelection}
                  className="w-4 h-4 rounded border-border-subtle accent-gold-primary"
                />
              </div>
              <HeaderCell className="flex-1">Title</HeaderCell>
              <HeaderCell className="w-[120px]">Type</HeaderCell>
              <HeaderCell className="w-[80px]">Version</HeaderCell>
              <HeaderCell className="w-[120px]">Status</HeaderCell>
              <HeaderCell className="w-[80px] text-center">Indexed</HeaderCell>
              <HeaderCell className="w-[120px]">Created</HeaderCell>
              <div className="w-12 sm:w-10" />
            </div>

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
              <div>
                {filteredDocs.map((doc, index) => (
                  <div
                    key={doc.document_id}
                    className={cn(
                      "flex h-12 min-w-[920px] items-center border-b border-border-subtle px-4 transition-colors duration-160",
                      index % 2 === 1 && "bg-[var(--surface-sunken)]/30",
                      "hover:bg-[var(--surface-sunken)]"
                    )}
                  >
                    <div className="flex w-12 items-center justify-center sm:w-10">
                      <input
                        type="checkbox"
                        checked={selectedDocs.includes(doc.document_id)}
                        onChange={() => toggleDocSelection(doc.document_id)}
                        className="w-4 h-4 rounded border-border-subtle accent-gold-primary"
                      />
                    </div>

                    <div className="flex-1 flex items-center gap-2 min-w-0">
                      <FileText
                        className="w-4 h-4 text-ink-tertiary"
                        strokeWidth={1.5}
                      />
                      <span className="text-[13px] font-medium text-ink-primary truncate">
                        {doc.title}
                      </span>
                    </div>

                    <DataCell className="w-[120px]">{formatDocumentType(doc.document_type)}</DataCell>
                    <DataCell className="w-[80px] accent">{`v${doc.version}`}</DataCell>
                    <div className="w-[120px]">
                      <StatusBadge status={doc.status} />
                    </div>
                    <div className="w-[80px] flex justify-center">
                      <IndexedIndicator indexed={Boolean(doc.vector_indexed_at)} />
                    </div>
                    <DataCell className="w-[120px]">{formatDate(doc.created_at)}</DataCell>

                    <div className="flex w-12 justify-center sm:w-10">
                      <ActionMenu
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
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="flex min-h-12 min-w-[920px] flex-col gap-3 border-t border-border-subtle bg-surface-raised px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-[13px] text-ink-secondary">
                Showing {filteredDocs.length} of {data.total} documents
              </span>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle text-ink-secondary transition-colors hover:bg-[var(--surface-sunken)] disabled:cursor-not-allowed disabled:opacity-50 sm:h-8 sm:w-8"
                  aria-label="Previous page"
                >
                  <ChevronLeft className="w-4 h-4" strokeWidth={1.5} />
                </button>

                <span className="font-mono text-[11px] text-ink-secondary tabular-nums px-2">
                  {currentPage} / {totalPages}
                </span>

                <button
                  onClick={() =>
                    setCurrentPage((p) => Math.min(totalPages, p + 1))
                  }
                  disabled={currentPage === totalPages}
                  className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle text-ink-secondary transition-colors hover:bg-[var(--surface-sunken)] disabled:cursor-not-allowed disabled:opacity-50 sm:h-8 sm:w-8"
                  aria-label="Next page"
                >
                  <ChevronRight className="w-4 h-4" strokeWidth={1.5} />
                </button>
              </div>
            </div>
          </div>
        </div>
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
            <NoticeState
              title={modal.title}
              message={modal.message}
              onClose={closeModal}
            />
          )}
          {modal.type === "upload" && (
            <DocumentForm
              title="Upload Document"
              submitLabel="Create document"
              error={formError}
              isSubmitting={isSubmitting}
              onSubmit={handleCreateDocument}
            />
          )}
          {modal.type === "view" && (
            <DocumentDetail document={modal.document} />
          )}
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
    </div>
  );
}

function ActionMenu({
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
        onClick={() => setIsOpen(!isOpen)}
        className="flex h-11 w-11 items-center justify-center rounded transition-colors duration-160 hover:bg-[var(--gold-bg)] sm:h-8 sm:w-8"
        aria-label="Document actions"
      >
        <MoreHorizontal className="w-4 h-4 text-ink-tertiary" strokeWidth={1.5} />
      </button>
      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 w-44 bg-surface border border-border-subtle rounded-lg shadow-lg overflow-hidden">
            <MenuAction icon={Eye} label="View" onClick={onView} close={() => setIsOpen(false)} />
            <MenuAction icon={Pencil} label="Edit" onClick={onEdit} close={() => setIsOpen(false)} />
            <MenuAction icon={History} label="Version History" onClick={onHistory} close={() => setIsOpen(false)} />
            <MenuAction
              icon={Upload}
              label={ingestBusy ? "Indexing" : "Ingest"}
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
      onClick={() => {
        onClick();
        close();
      }}
      className={cn(
        "flex min-h-11 w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors hover:bg-[var(--gold-bg)]",
        danger ? "text-red-alert hover:bg-[rgba(220,38,38,0.06)]" : "text-ink-secondary"
      )}
    >
      <Icon className="w-4 h-4" strokeWidth={1.5} />
      {label}
    </button>
  );
}

function HeaderCell({ children, className }: { children: React.ReactNode; className: string }) {
  return (
    <div className={cn("font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary", className)}>
      {children}
    </div>
  );
}

function DataCell({
  children,
  className,
  accent = false,
}: {
  children: React.ReactNode;
  className: string;
  accent?: boolean;
}) {
  return (
    <div className={className}>
      <span className={cn("font-mono text-[11px]", accent ? "text-gold-primary tabular-nums" : "text-ink-secondary")}>
        {children}
      </span>
    </div>
  );
}

function StatusBadge({ status }: { status: TenantKnowledgeDocument["status"] }) {
  const config = {
    active: {
      icon: Check,
      label: "Active",
      bg: "bg-[rgba(22,163,74,0.08)]",
      text: "text-green-success",
    },
    archived: {
      icon: X,
      label: "Archived",
      bg: "bg-[rgba(107,114,128,0.08)]",
      text: "text-ink-tertiary",
    },
    pending_index: {
      icon: Clock,
      label: "Pending",
      bg: "bg-[rgba(184,130,28,0.08)]",
      text: "text-warning-amber",
    },
    indexing: {
      icon: AlertTriangle,
      label: "Indexing",
      bg: "bg-[rgba(59,130,246,0.08)]",
      text: "text-blue-system",
    },
  };

  const { icon: Icon, label, bg, text } = config[status];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full",
        "font-mono text-[11px] uppercase tracking-[0.12em]",
        bg,
        text
      )}
    >
      <Icon className="w-3 h-3" strokeWidth={1.5} />
      {label}
    </span>
  );
}

function IndexedIndicator({ indexed }: { indexed: boolean }) {
  return (
    <span
      className={cn("w-2 h-2 rounded-full", indexed ? "bg-green-success" : "bg-ink-tertiary")}
      title={indexed ? "Indexed" : "Not indexed"}
    />
  );
}

function Modal({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 sm:p-6">
      <div className="max-h-[88dvh] w-full max-w-3xl overflow-y-auto rounded-lg border border-border-subtle bg-surface p-4 shadow-elevated sm:p-6">
        <div className="mb-4 flex justify-end">
          <button
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle text-ink-tertiary hover:text-ink-primary"
            aria-label="Close modal"
          >
            <X className="h-4 w-4" strokeWidth={1.5} />
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
      <h2 className="font-serif text-[28px] font-semibold text-ink-primary">{title}</h2>
      {error && (
        <div className="rounded border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
          {error}
        </div>
      )}
      <label className="block">
        <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
          Title
        </span>
        <input
          name="title"
          defaultValue={document?.title ?? ""}
          disabled={Boolean(document)}
          required
          className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary disabled:opacity-60 sm:h-10"
        />
      </label>
      <label className="block">
        <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
          Document type
        </span>
        <select
          name="document_type"
          defaultValue={document?.document_type ?? "sop"}
          disabled={Boolean(document)}
          className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary disabled:opacity-60 sm:h-10"
        >
          {documentTypes.filter((type) => type.id !== "all").map((type) => (
            <option key={type.id} value={type.id}>
              {type.label}
            </option>
          ))}
        </select>
      </label>
      {document && (
        <label className="block">
          <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
            Status
          </span>
          <select
            name="status"
            defaultValue={document.status}
            className="h-11 w-full rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
          >
            <option value="active">Active</option>
            <option value="pending_index">Pending index</option>
            <option value="indexing">Indexing</option>
            <option value="archived">Archived</option>
          </select>
        </label>
      )}
      <label className="block">
        <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
          Content
        </span>
        <textarea
          name="content"
          defaultValue={document?.content ?? ""}
          required
          rows={10}
          className="w-full rounded border border-border-subtle bg-surface-raised px-3 py-2 text-[14px] leading-relaxed text-ink-primary focus:outline-none focus:border-gold-primary"
        />
      </label>
      <button
        type="submit"
        disabled={isSubmitting}
        className="inline-flex min-h-11 items-center justify-center rounded bg-gold-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-gold-muted disabled:opacity-60"
      >
        {isSubmitting ? "Submitting..." : submitLabel}
      </button>
    </form>
  );
}

function DocumentDetail({ document }: { document: TenantKnowledgeDocument }) {
  return (
    <div className="space-y-4">
      <h2 className="font-serif text-[28px] font-semibold text-ink-primary">{document.title}</h2>
      <div className="grid grid-cols-1 gap-3 text-[13px] sm:grid-cols-2">
        <Detail label="Document ID" value={document.document_id} />
        <Detail label="Type" value={formatDocumentType(document.document_type)} />
        <Detail label="Version" value={`v${document.version}`} />
        <Detail label="Status" value={document.status} />
        <Detail label="Uploaded by" value={document.uploaded_by} />
        <Detail label="Created" value={formatDate(document.created_at)} />
      </div>
      <div className="max-h-[360px] overflow-auto whitespace-pre-wrap rounded border border-border-subtle bg-surface-raised p-4 text-[13px] leading-relaxed text-ink-body">
        {document.content}
      </div>
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
    return (
      <ErrorState
        title="Version history unavailable"
        message={modal.error}
        onAction={onRetry}
      />
    );
  }
  return (
    <div className="space-y-4">
      <h2 className="font-serif text-[28px] font-semibold text-ink-primary">
        Version History
      </h2>
      <p className="text-[14px] text-ink-secondary">{modal.document.title}</p>
      {modal.versions.length === 0 ? (
        <EmptyState
          title="No versions returned"
          message="The cognition version endpoint returned no historical versions for this document."
        />
      ) : (
        <div className="space-y-3">
          {modal.versions.map((version) => (
            <div
              key={version.version_id}
              className="rounded border border-border-subtle bg-surface-raised p-4"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[12px] text-gold-primary">
                  v{version.version}
                </span>
                <span className="font-mono text-[11px] text-ink-tertiary">
                  {formatDate(version.created_at)}
                </span>
              </div>
              <p className="mt-2 text-[14px] font-medium text-ink-primary">
                {version.title}
              </p>
              <p className="mt-1 line-clamp-3 text-[13px] leading-relaxed text-ink-secondary">
                {version.content}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NoticeState({
  title,
  message,
  onClose,
}: {
  title: string;
  message: string;
  onClose: () => void;
}) {
  return (
    <div className="space-y-4">
      <h2 className="font-serif text-[28px] font-semibold text-ink-primary">{title}</h2>
      <p className="text-[14px] leading-relaxed text-ink-secondary">{message}</p>
      <button
        onClick={onClose}
        className="inline-flex min-h-11 items-center justify-center rounded bg-gold-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-gold-muted"
      >
        Close
      </button>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-surface-raised p-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </div>
      <div className="mt-1 break-words text-ink-primary">{value}</div>
    </div>
  );
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
