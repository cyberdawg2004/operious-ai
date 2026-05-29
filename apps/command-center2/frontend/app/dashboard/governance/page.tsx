import { CrisisControlPanel } from "@/components/crisis-control-panel";
import { GovernancePoliciesView } from "@/components/integration-views";

export default function DashboardGovernancePage() {
  return <GovernancePoliciesView headerAddon={<CrisisControlPanel />} />;
}
