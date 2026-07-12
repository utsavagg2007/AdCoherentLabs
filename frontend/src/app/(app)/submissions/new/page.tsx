import { requireContext } from "@/lib/data";
import { getPlans } from "@/lib/data";
import { frameworksLabel } from "@/lib/entitlements";
import { PageHeader } from "@/components/page-header";
import { NewSubmissionWizard } from "./wizard";

export const metadata = { title: "New submission" };

export default async function NewSubmissionPage() {
  const ctx = await requireContext();
  const plans = await getPlans();
  const plan = plans.find((p) => p.tier === ctx.quota.tier);
  const canSubmit = ["owner", "admin", "reviewer"].includes(ctx.role);

  return (
    <>
      <PageHeader
        title="New submission"
        description="Upload creatives or point at a landing page — the engine handles framework routing."
      />
      <NewSubmissionWizard
        orgId={ctx.org.id}
        quota={ctx.quota}
        demo={ctx.demo}
        canSubmit={canSubmit}
        frameworks={frameworksLabel(plan?.frameworks ?? "all")}
      />
    </>
  );
}
