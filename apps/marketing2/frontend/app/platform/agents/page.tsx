import { PageShell } from "@/components/page-shell";
import { pages } from "@/lib/page-content";

export default function AgentsPage() {
  return <PageShell content={pages.platformAgents} />;
}
