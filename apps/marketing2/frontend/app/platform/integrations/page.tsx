import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Integrations - Operious AI",
  description:
    "Integration matrix for Operious across helpdesk, CRM, telephony, messaging, issue tracking, ecommerce, and ERP systems.",
};

const integrations = [
  ["Zendesk", "Helpdesk/CX", "Channel adapter + webhook", "Available"],
  ["Salesforce", "CRM", "Outbound webhook + events", "Available"],
  ["ServiceNow", "ITSM", "Outbound webhook", "Available"],
  ["Jira", "Issue tracking", "Governed dispatch", "Available"],
  ["Linear", "Issue tracking", "Governed dispatch", "Available"],
  ["Twilio", "Voice/SMS", "Media streams", "Available"],
  ["WhatsApp Biz", "Messaging", "Cloud API", "Available"],
  ["Email (SES/SMTP)", "Email", "Inbound/outbound", "Available"],
  ["Shulex", "E-commerce CX", "Webhook adapter", "Available"],
  ["Lark", "Messaging", "Webhook adapter", "Available"],
  ["Shopify", "E-commerce", "Read-only enrichment", "Available"],
  ["Slack", "Internal", "Notification channel", "Roadmap"],
  ["SAP", "ERP", "Webhook", "Roadmap"],
] as const;

export default function IntegrationsPage() {
  return (
    <main className="flex-1 overflow-x-hidden">
      <section className="bg-canvas px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-36 lg:px-16 lg:pb-24">
        <div className="mx-auto max-w-[1120px]">
          <p
            className="text-[10px] uppercase tracking-[0.18em] text-gold"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            Platform / Integrations
          </p>
          <h1
            className="mt-5 max-w-[940px] text-[42px] font-bold leading-[1.05] text-ink-primary sm:text-[56px] lg:text-[72px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Operious connects to your existing stack. Every integration is governed.
          </h1>
          <p className="mt-6 max-w-[820px] text-[18px] leading-relaxed text-ink-secondary sm:text-[20px]">
            No rip and replace. Operious operates as the governance layer alongside
            your existing helpdesk, CRM, telephony, and issue-tracking infrastructure.
          </p>
        </div>
      </section>

      <section className="bg-surface-raised px-4 py-16 sm:px-8 sm:py-20 lg:px-16">
        <div className="mx-auto max-w-[1120px] overflow-hidden rounded-md border border-border-subtle bg-white">
          <div className="overflow-x-auto">
            <table className="min-w-[820px] w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-border-subtle bg-surface text-[11px] uppercase tracking-[0.14em] text-ink-tertiary">
                  <th className="px-5 py-4">System</th>
                  <th className="px-5 py-4">Category</th>
                  <th className="px-5 py-4">Integration Type</th>
                  <th className="px-5 py-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {integrations.map(([system, category, type, status]) => (
                  <tr
                    key={system}
                    className="border-b border-border-subtle text-[15px] text-ink-body last:border-b-0"
                  >
                    <td className="px-5 py-4 font-semibold text-ink-primary">{system}</td>
                    <td className="px-5 py-4">{category}</td>
                    <td className="px-5 py-4">{type}</td>
                    <td className="px-5 py-4">
                      <span className="rounded border border-gold/25 bg-gold/10 px-2 py-1 text-[12px] font-medium text-gold">
                        {status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="mx-auto mt-8 max-w-[1120px] rounded-md border border-border-subtle bg-white p-6">
          <p className="max-w-[860px] text-[16px] leading-relaxed text-ink-body">
            All integrations pass through the Operious governance layer. Outbound
            data is never transmitted without a persisted governance authorization
            decision. Tenant credentials are encrypted and never returned in API
            responses.
          </p>
        </div>
      </section>
    </main>
  );
}
