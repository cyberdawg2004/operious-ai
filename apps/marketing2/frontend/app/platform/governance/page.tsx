import { PageShell } from "@/components/page-shell";
import { pages } from "@/lib/page-content";

export default function GovernancePage() {
  return <PageShell content={pages.platformGovernance} />;
}
