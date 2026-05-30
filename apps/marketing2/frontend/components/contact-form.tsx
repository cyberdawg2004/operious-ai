"use client";

import { useState } from "react";
import { Send } from "lucide-react";

const domains = [
  "Hardware",
  "Financial services",
  "Healthcare",
  "Insurance",
  "Telecommunications",
  "Logistics",
  "Public sector",
  "Other regulated operations",
];

const currentSystemOptions = [
  "Zendesk",
  "Salesforce Service Cloud",
  "ServiceNow",
  "Freshdesk",
  "Intercom",
  "Proprietary / internal",
  "Other",
];

const automationInterestOptions = [
  "Warranty and claims",
  "Refund authorization",
  "Escalation routing",
  "Multilingual support",
  "Compliance documentation",
  "Other",
];

const timelineOptions = [
  "Active evaluation (< 30 days)",
  "Planning phase (1-3 months)",
  "Research only",
];

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; message: string; requestId: string }
  | { status: "error"; message: string };

export function ContactForm({
  initialDomain,
  context,
}: {
  initialDomain?: string;
  context?: string;
}) {
  const [submitState, setSubmitState] = useState<SubmitState>({ status: "idle" });

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitState({ status: "submitting" });

    const formData = new FormData(event.currentTarget);
    const payload = Object.fromEntries(formData.entries());

    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = (await response.json()) as {
        message?: string;
        error?: string;
        requestId?: string;
      };

      if (!response.ok) {
        if (response.status === 503) {
          throw new Error(
            "Our contact intake is currently unavailable. Please email sales@operious.com and a solutions architect will respond within one business day."
          );
        }

        throw new Error(
          result.message ?? result.error ?? "The request could not be submitted."
        );
      }

      setSubmitState({
        status: "success",
        message:
          result.message ??
          "Your request was received. Operious will follow up with architecture review next steps.",
        requestId: result.requestId ?? "pending",
      });
      event.currentTarget.reset();
    } catch (error) {
      setSubmitState({
        status: "error",
        message: error instanceof Error ? error.message : "The request could not be submitted.",
      });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-5 rounded-md border border-border-subtle bg-white p-6 sm:p-8">
      {context && <input type="hidden" name="context" value={context} />}
      <div className="grid gap-5 sm:grid-cols-2">
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Name
          <input
            required
            name="name"
            autoComplete="name"
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          />
        </label>
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Company
          <input
            required
            name="company"
            autoComplete="organization"
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          />
        </label>
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Email
          <input
            required
            type="email"
            name="email"
            autoComplete="email"
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          />
        </label>
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Role
          <input
            required
            name="role"
            autoComplete="organization-title"
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          />
        </label>
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Operational domain
          <select
            required
            name="domain"
            defaultValue={initialDomain ?? ""}
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          >
            <option value="" disabled>
              Select a domain
            </option>
            {domains.map((domain) => (
              <option key={domain} value={domain}>
                {domain}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Estimated ticket volume
          <input
            required
            name="ticketVolume"
            placeholder="Example: 50,000 per month"
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          />
        </label>
      </div>
      <label className="grid gap-2 text-[13px] font-medium text-ink-body">
        Brief description of use case
        <textarea
          required
          name="useCase"
          rows={6}
          className="rounded-md border border-border-defined px-3 py-3 text-[15px] text-ink-primary"
        />
      </label>
      <div className="grid gap-5 sm:grid-cols-3">
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Primary support or operations platform
          <select
            name="currentSystems"
            defaultValue=""
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          >
            <option value="">Select if known</option>
            {currentSystemOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Primary workflow to automate
          <select
            name="automationInterest"
            defaultValue=""
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          >
            <option value="">Select if known</option>
            {automationInterestOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-[13px] font-medium text-ink-body">
          Evaluation timeline
          <select
            name="timeline"
            defaultValue=""
            className="h-11 rounded-md border border-border-defined px-3 text-[15px] text-ink-primary"
          >
            <option value="">Select if known</option>
            {timelineOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      </div>

      {submitState.status === "success" && (
        <p className="rounded-md border border-status-success/30 bg-status-success/10 p-3 text-[14px] text-status-success">
          {submitState.message} Request ID: {submitState.requestId}
        </p>
      )}
      {submitState.status === "error" && (
        <p className="rounded-md border border-status-error/30 bg-status-error/10 p-3 text-[14px] text-status-error">
          {submitState.message}
        </p>
      )}

      <button
        type="submit"
        disabled={submitState.status === "submitting"}
        className="inline-flex h-12 items-center justify-center rounded-md bg-ink-primary px-5 text-[14px] font-semibold text-white transition-colors hover:bg-ink-body disabled:cursor-wait disabled:opacity-70"
      >
        {submitState.status === "submitting" ? "Submitting request" : "Book an Architecture Review"}
        <Send className="ml-2 h-4 w-4" />
      </button>
      <p className="text-[12px] leading-relaxed text-ink-tertiary">
        A solutions architect reviews every request. Response within one business day.
        For urgent inquiries: sales@operious.com
      </p>
    </form>
  );
}
