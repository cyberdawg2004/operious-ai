"use client";

import { useState } from "react";
import {
  Search,
  Upload,
  Folder,
  FileText,
  MoreHorizontal,
  Check,
  Clock,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Eye,
  Pencil,
  Trash2,
  History,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Types
interface Category {
  id: string;
  label: string;
  count: number;
}

interface Document {
  id: string;
  title: string;
  type: string;
  version: string;
  status: "published" | "draft" | "review";
  indexed: boolean;
  lastUpdated: string;
}

// Mock data
const categories: Category[] = [
  { id: "all", label: "All Documents", count: 247 },
  { id: "sops", label: "SOPs", count: 142 },
  { id: "policies", label: "Policies", count: 38 },
  { id: "product-guides", label: "Product Guides", count: 41 },
  { id: "faqs", label: "FAQs", count: 18 },
  { id: "escalation", label: "Escalation Matrices", count: 8 },
  { id: "archived", label: "Archived", count: 12 },
];

const documents: Document[] = [
  {
    id: "SOP-2024-001",
    title: "Customer Onboarding Process",
    type: "SOP",
    version: "v3.2",
    status: "published",
    indexed: true,
    lastUpdated: "2024-01-15",
  },
  {
    id: "SOP-2024-002",
    title: "Refund Request Handling",
    type: "SOP",
    version: "v2.1",
    status: "published",
    indexed: true,
    lastUpdated: "2024-01-14",
  },
  {
    id: "SOP-2024-003",
    title: "Technical Support Escalation",
    type: "SOP",
    version: "v4.0",
    status: "draft",
    indexed: false,
    lastUpdated: "2024-01-13",
  },
  {
    id: "SOP-2024-004",
    title: "Account Verification Steps",
    type: "SOP",
    version: "v1.5",
    status: "review",
    indexed: false,
    lastUpdated: "2024-01-12",
  },
  {
    id: "SOP-2024-005",
    title: "Billing Dispute Resolution",
    type: "SOP",
    version: "v2.8",
    status: "published",
    indexed: true,
    lastUpdated: "2024-01-11",
  },
  {
    id: "SOP-2024-006",
    title: "Password Reset Procedure",
    type: "SOP",
    version: "v1.2",
    status: "published",
    indexed: true,
    lastUpdated: "2024-01-10",
  },
  {
    id: "SOP-2024-007",
    title: "Product Return Guidelines",
    type: "SOP",
    version: "v3.0",
    status: "published",
    indexed: true,
    lastUpdated: "2024-01-09",
  },
  {
    id: "SOP-2024-008",
    title: "VIP Customer Handling",
    type: "SOP",
    version: "v2.0",
    status: "draft",
    indexed: false,
    lastUpdated: "2024-01-08",
  },
];

// Status badge component
function StatusBadge({ status }: { status: Document["status"] }) {
  const config = {
    published: {
      icon: Check,
      label: "Published",
      bg: "bg-[rgba(22,163,74,0.08)]",
      text: "text-green-success",
    },
    draft: {
      icon: Clock,
      label: "Draft",
      bg: "bg-[rgba(107,114,128,0.08)]",
      text: "text-ink-tertiary",
    },
    review: {
      icon: AlertTriangle,
      label: "In Review",
      bg: "bg-[rgba(184,130,28,0.08)]",
      text: "text-warning-amber",
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

// Indexed indicator
function IndexedIndicator({ indexed }: { indexed: boolean }) {
  return (
    <span
      className={cn(
        "w-2 h-2 rounded-full",
        indexed ? "bg-green-success" : "bg-ink-tertiary"
      )}
      title={indexed ? "Indexed" : "Not indexed"}
    />
  );
}

// Action menu component
function ActionMenu({ onAction }: { onAction: (action: string) => void }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="p-1 rounded hover:bg-[rgba(168,136,44,0.06)] transition-colors duration-160"
      >
        <MoreHorizontal className="w-4 h-4 text-ink-tertiary" strokeWidth={1.5} />
      </button>
      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute right-0 top-full mt-1 z-20 w-40 bg-surface border border-border-subtle rounded-lg shadow-lg overflow-hidden">
            <button
              onClick={() => {
                onAction("view");
                setIsOpen(false);
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-left text-[13px] text-ink-secondary hover:bg-[rgba(168,136,44,0.06)] transition-colors"
            >
              <Eye className="w-4 h-4" strokeWidth={1.5} />
              View
            </button>
            <button
              onClick={() => {
                onAction("edit");
                setIsOpen(false);
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-left text-[13px] text-ink-secondary hover:bg-[rgba(168,136,44,0.06)] transition-colors"
            >
              <Pencil className="w-4 h-4" strokeWidth={1.5} />
              Edit
            </button>
            <button
              onClick={() => {
                onAction("history");
                setIsOpen(false);
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-left text-[13px] text-ink-secondary hover:bg-[rgba(168,136,44,0.06)] transition-colors"
            >
              <History className="w-4 h-4" strokeWidth={1.5} />
              Version History
            </button>
            <button
              onClick={() => {
                onAction("delete");
                setIsOpen(false);
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-left text-[13px] text-red-alert hover:bg-[rgba(220,38,38,0.06)] transition-colors"
            >
              <Trash2 className="w-4 h-4" strokeWidth={1.5} />
              Delete
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function KnowledgeBase() {
  const [activeCategory, setActiveCategory] = useState("sops");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [currentPage, setCurrentPage] = useState(1);

  const filteredDocs = documents.filter((doc) =>
    doc.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const totalPages = Math.ceil(filteredDocs.length / 10);

  const toggleDocSelection = (id: string) => {
    setSelectedDocs((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    );
  };

  const toggleAllSelection = () => {
    if (selectedDocs.length === filteredDocs.length) {
      setSelectedDocs([]);
    } else {
      setSelectedDocs(filteredDocs.map((d) => d.id));
    }
  };

  return (
    <div className="flex-1 bg-canvas py-8 px-12 overflow-auto">
      {/* Header */}
      <div className="mb-8">
        {/* Breadcrumb */}
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary mb-2">
          Knowledge · Document Management
        </p>

        {/* Title row */}
        <div className="flex items-center justify-between">
          <h1 className="font-serif text-[32px] font-bold text-ink-primary">
            Knowledge Base
          </h1>

          {/* Actions */}
          <div className="flex items-center gap-3">
            {/* Search */}
            <div className="relative w-[280px]">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-tertiary"
                strokeWidth={1.5}
              />
              <input
                type="text"
                placeholder="Search documents..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full h-9 pl-9 pr-3 bg-surface border border-border-subtle rounded-lg text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none focus:border-gold-accent transition-colors"
              />
            </div>

            {/* Upload button */}
            <button className="flex items-center gap-2 h-9 px-4 bg-gold-accent text-ink-primary rounded font-sans text-[13px] font-medium hover:bg-[#9A7A28] transition-colors duration-160">
              <Upload className="w-3.5 h-3.5" strokeWidth={1.5} />
              Upload Document
            </button>
          </div>
        </div>
      </div>

      {/* Two column layout */}
      <div className="flex gap-6">
        {/* Left column - Category tree */}
        <div className="w-60 flex-shrink-0">
          <div className="bg-surface border border-border-subtle rounded-lg p-4">
            <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary mb-4">
              Categories
            </h2>

            <div className="space-y-1">
              {categories.map((category) => (
                <button
                  key={category.id}
                  onClick={() => setActiveCategory(category.id)}
                  className={cn(
                    "w-full h-9 px-3 flex items-center gap-2 rounded transition-colors duration-160",
                    activeCategory === category.id
                      ? "bg-[rgba(168,136,44,0.06)] border-l-4 border-l-gold-accent -ml-px"
                      : "hover:bg-[rgba(168,136,44,0.04)]"
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
                  <span className="font-mono text-[11px] text-ink-tertiary">
                    {category.count}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right column - Document table */}
        <div className="flex-1 bg-surface border border-border-subtle rounded-lg overflow-hidden">
          {/* Table header */}
          <div className="h-10 px-4 flex items-center bg-surface-raised border-b border-border-subtle">
            <div className="w-10 flex items-center justify-center">
              <input
                type="checkbox"
                checked={
                  selectedDocs.length === filteredDocs.length &&
                  filteredDocs.length > 0
                }
                onChange={toggleAllSelection}
                className="w-4 h-4 rounded border-border-subtle accent-gold-accent"
              />
            </div>
            <div className="flex-1 font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
              Title
            </div>
            <div className="w-[100px] font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
              Type
            </div>
            <div className="w-[80px] font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
              Version
            </div>
            <div className="w-[100px] font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
              Status
            </div>
            <div className="w-[80px] font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary text-center">
              Indexed
            </div>
            <div className="w-[100px] font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
              Last Updated
            </div>
            <div className="w-10" />
          </div>

          {/* Table body */}
          <div>
            {filteredDocs.map((doc, index) => (
              <div
                key={doc.id}
                className={cn(
                  "h-12 px-4 flex items-center border-b border-border-subtle transition-colors duration-160",
                  index % 2 === 1 && "bg-[rgba(168,136,44,0.02)]",
                  "hover:bg-[rgba(168,136,44,0.04)]"
                )}
              >
                {/* Checkbox */}
                <div className="w-10 flex items-center justify-center">
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(doc.id)}
                    onChange={() => toggleDocSelection(doc.id)}
                    className="w-4 h-4 rounded border-border-subtle accent-gold-accent"
                  />
                </div>

                {/* Title */}
                <div className="flex-1 flex items-center gap-2">
                  <FileText
                    className="w-4 h-4 text-ink-tertiary"
                    strokeWidth={1.5}
                  />
                  <span className="text-[13px] font-medium text-ink-primary truncate">
                    {doc.title}
                  </span>
                </div>

                {/* Type */}
                <div className="w-[100px]">
                  <span className="font-mono text-[11px] text-ink-secondary">
                    {doc.type}
                  </span>
                </div>

                {/* Version */}
                <div className="w-[80px]">
                  <span className="font-mono text-[11px] text-gold-accent tabular-nums">
                    {doc.version}
                  </span>
                </div>

                {/* Status */}
                <div className="w-[100px]">
                  <StatusBadge status={doc.status} />
                </div>

                {/* Indexed */}
                <div className="w-[80px] flex justify-center">
                  <IndexedIndicator indexed={doc.indexed} />
                </div>

                {/* Last Updated */}
                <div className="w-[100px]">
                  <span className="font-mono text-[11px] text-ink-tertiary tabular-nums">
                    {doc.lastUpdated}
                  </span>
                </div>

                {/* Actions */}
                <div className="w-10 flex justify-center">
                  <ActionMenu onAction={(action) => console.log(action, doc.id)} />
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          <div className="h-12 px-4 flex items-center justify-between bg-surface-raised border-t border-border-subtle">
            <span className="text-[13px] text-ink-secondary">
              Showing {filteredDocs.length} of {documents.length} documents
            </span>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="w-8 h-8 flex items-center justify-center rounded border border-border-subtle text-ink-secondary hover:bg-[rgba(168,136,44,0.04)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="w-4 h-4" strokeWidth={1.5} />
              </button>

              <span className="font-mono text-[11px] text-ink-secondary tabular-nums px-2">
                {currentPage} / {totalPages || 1}
              </span>

              <button
                onClick={() =>
                  setCurrentPage((p) => Math.min(totalPages, p + 1))
                }
                disabled={currentPage === totalPages || totalPages === 0}
                className="w-8 h-8 flex items-center justify-center rounded border border-border-subtle text-ink-secondary hover:bg-[rgba(168,136,44,0.04)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight className="w-4 h-4" strokeWidth={1.5} />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
