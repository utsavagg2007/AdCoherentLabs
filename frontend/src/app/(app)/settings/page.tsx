import { requireContext, getMembers } from "@/lib/data";
import { PageHeader } from "@/components/page-header";
import { OrgSettingsForm } from "./org-form";
import { MembersPanel } from "./members-panel";

export const metadata = { title: "Settings" };

export default async function SettingsPage() {
  const ctx = await requireContext();
  const members = await getMembers(ctx.org.id);
  const isAdmin = ctx.role === "owner" || ctx.role === "admin";

  return (
    <>
      <PageHeader
        title="Settings"
        description={`Organization and team for ${ctx.org.name}.`}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <div>
          <OrgSettingsForm orgName={ctx.org.name} canEdit={isAdmin} />
        </div>
        <div className="lg:col-span-2">
          <MembersPanel
            members={members}
            selfId={ctx.user.id}
            canManage={isAdmin}
          />
        </div>
      </div>
    </>
  );
}
