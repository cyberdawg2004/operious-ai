import { PageShell } from "@/components/page-shell";
import { pages } from "@/lib/page-content";

export default function CompliancePage() {
  return <PageShell content={pages.trustCompliance} />;
}
