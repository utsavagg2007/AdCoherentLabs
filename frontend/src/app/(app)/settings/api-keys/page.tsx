import Link from "next/link";
import { requireContext, getApiKeys } from "@/lib/data";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { buttonClasses } from "@/components/ui/button";
import { ApiKeysPanel } from "./api-keys-panel";

export const metadata = { title: "API Keys" };

export default async function ApiKeysPage() {
  const ctx = await requireContext();

  if (!ctx.quota.api_access) {
    return (
      <>
        <PageHeader
          title="API Keys"
          description="Programmatic access to the compliance engine."
        />
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle>API access is a Pro+ entitlement</CardTitle>
            <CardDescription>
              The <code className="font-mono">/v1</code> API lets your CI or CMS
              submit creatives and read findings programmatically — same engine,
              API-key auth, rate-limited per key. Available on Pro, Design and
              Enterprise.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/billing" className={buttonClasses("primary", "sm")}>
              Upgrade to unlock
            </Link>
          </CardContent>
        </Card>
      </>
    );
  }

  const keys = await getApiKeys(ctx.org.id);
  const canManage = ctx.role === "owner" || ctx.role === "admin";

  return (
    <>
      <PageHeader
        title="API Keys"
        description="Keys are shown once and stored as a SHA-256 hash — treat them like passwords."
      />
      <ApiKeysPanel keys={keys} canManage={canManage} />
    </>
  );
}
