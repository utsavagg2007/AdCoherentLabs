"use server";

import { createHash, randomBytes } from "crypto";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { isDemoMode, siteUrl } from "@/lib/env";
import { ACTIVE_ORG_COOKIE, getSessionState } from "@/lib/data";
import type { ActionResult, AssetKind, FindingStatus, Role } from "@/lib/types";

const DEMO_BLOCK: ActionResult = {
  ok: false,
  message: "Demo mode — connect Supabase to enable writes (see README.md).",
};

const REVIEWER_ROLES: Role[] = ["owner", "admin", "reviewer"];
const ADMIN_ROLES: Role[] = ["owner", "admin"];

async function requireOrgRole(allowed: Role[]) {
  const state = await getSessionState();
  if (state.kind !== "ready") throw new Error("Not signed in.");
  const { ctx } = state;
  if (!allowed.includes(ctx.role)) {
    throw new Error(`Your role (${ctx.role}) does not permit this action.`);
  }
  return ctx;
}

function fail(e: unknown): ActionResult {
  return { ok: false, message: e instanceof Error ? e.message : String(e) };
}

// ── Orgs ─────────────────────────────────────────────────────────────────────

export async function createOrg(name: string): Promise<ActionResult<{ orgId: string }>> {
  if (isDemoMode) return DEMO_BLOCK;
  const trimmed = name.trim();
  if (trimmed.length < 2) return { ok: false, message: "Name the organization (2+ characters)." };

  const supabase = await createClient();
  // app.create_org() via its public wrapper (db/0007_app_rpc_wrappers.sql).
  const { data, error } = await supabase.rpc("create_org", { org_name: trimmed });
  if (error) {
    return {
      ok: false,
      message:
        error.code === "PGRST202"
          ? "The create_org RPC is not exposed. Apply frontend/db/0007_app_rpc_wrappers.sql to the database (see README.md)."
          : error.message,
    };
  }
  const orgId = data as string;
  const cookieStore = await cookies();
  cookieStore.set(ACTIVE_ORG_COOKIE, orgId, { path: "/", sameSite: "lax" });
  return { ok: true, data: { orgId } };
}

export async function setActiveOrg(orgId: string): Promise<void> {
  if (!isDemoMode) {
    const state = await getSessionState();
    if (state.kind !== "ready" || !state.ctx.orgs.some((o) => o.id === orgId)) {
      return; // never trust a client-supplied org id
    }
    const cookieStore = await cookies();
    cookieStore.set(ACTIVE_ORG_COOKIE, orgId, { path: "/", sameSite: "lax" });
  }
  revalidatePath("/", "layout");
  redirect("/dashboard");
}

export async function updateOrgName(name: string): Promise<ActionResult> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(ADMIN_ROLES);
    const supabase = await createClient();
    const { error } = await supabase
      .from("orgs")
      .update({ name: name.trim() })
      .eq("id", ctx.org.id);
    if (error) throw new Error(error.message);
    revalidatePath("/settings");
    revalidatePath("/", "layout");
    return { ok: true, message: "Organization renamed." };
  } catch (e) {
    return fail(e);
  }
}

// ── Submissions & runs ───────────────────────────────────────────────────────

export async function createSubmission(
  title: string,
): Promise<ActionResult<{ submissionId: string; orgId: string }>> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(REVIEWER_ROLES);
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("submissions")
      .insert({
        org_id: ctx.org.id,
        created_by: ctx.user.id,
        title: title.trim() || "Untitled submission",
      })
      .select("id")
      .single();
    if (error) throw new Error(error.message);
    return { ok: true, data: { submissionId: data.id, orgId: ctx.org.id } };
  } catch (e) {
    return fail(e);
  }
}

export interface AssetInput {
  kind: AssetKind;
  storage_path?: string;
  source_url?: string;
  checksum?: string;
}

/**
 * Registers uploaded assets, enforces quota BEFORE the expensive work
 * (playbook Phase 4), and enqueues the analysis run. The worker picks the
 * run up from `analysis_runs.status = 'queued'`.
 */
export async function startAnalysisRun(
  submissionId: string,
  assets: AssetInput[],
): Promise<ActionResult<{ runId: string }>> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(REVIEWER_ROLES);
    if (assets.length === 0) return { ok: false, message: "Add at least one asset." };

    const supabase = await createClient();

    // RLS re-checks org membership on this insert — defence in depth.
    const { error: assetError } = await supabase.from("assets").insert(
      assets.map((a) => ({
        submission_id: submissionId,
        org_id: ctx.org.id,
        kind: a.kind,
        storage_path: a.storage_path ?? null,
        source_url: a.source_url ?? null,
        checksum: a.checksum ?? null,
      })),
    );
    if (assetError) throw new Error(assetError.message);

    // Quota: atomic consume via service role (app.consume_scan_quota).
    const admin = createAdminClient();
    if (admin) {
      const { data: verdict, error } = await admin.rpc("consume_scan_quota", {
        target_org: ctx.org.id,
      });
      if (!error && verdict && (verdict as { allowed: boolean }).allowed === false) {
        const v = verdict as { used: number; limit: number };
        return {
          ok: false,
          message: `Monthly scan quota reached (${v.used}/${v.limit}). Upgrade your plan to continue.`,
        };
      }
      if (error && ctx.quota.remaining !== null && ctx.quota.remaining <= 0) {
        return { ok: false, message: "Monthly scan quota reached. Upgrade your plan to continue." };
      }
    } else if (ctx.quota.remaining !== null && ctx.quota.remaining <= 0) {
      // No service key configured — fall back to the read-side check.
      return { ok: false, message: "Monthly scan quota reached. Upgrade your plan to continue." };
    }

    const { data: run, error: runError } = await supabase
      .from("analysis_runs")
      .insert({
        submission_id: submissionId,
        org_id: ctx.org.id,
        status: "queued",
        tier: ctx.quota.tier,
      })
      .select("id")
      .single();
    if (runError) throw new Error(runError.message);

    revalidatePath("/dashboard");
    revalidatePath("/submissions");
    return { ok: true, data: { runId: run.id } };
  } catch (e) {
    return fail(e);
  }
}

// ── Findings review ──────────────────────────────────────────────────────────

export async function updateFindingStatus(
  findingId: string,
  status: FindingStatus,
): Promise<ActionResult> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(REVIEWER_ROLES);
    const supabase = await createClient();
    const { error } = await supabase
      .from("findings")
      .update({ status, reviewed_by: ctx.user.id })
      .eq("id", findingId)
      .eq("org_id", ctx.org.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  } catch (e) {
    return fail(e);
  }
}

// ── Members ──────────────────────────────────────────────────────────────────

export async function inviteMember(
  email: string,
  role: Role,
): Promise<ActionResult> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(ADMIN_ROLES);
    const admin = createAdminClient();
    if (!admin) {
      return {
        ok: false,
        message: "Member invites need SUPABASE_SERVICE_ROLE_KEY on the server (see README.md).",
      };
    }

    // Find or create the auth user.
    let userId: string | null = null;
    const { data: invited, error: inviteError } =
      await admin.auth.admin.inviteUserByEmail(email, {
        redirectTo: `${siteUrl}/auth/callback?next=/dashboard`,
      });
    if (invited?.user) {
      userId = invited.user.id;
    } else if (inviteError) {
      // Already registered — locate the existing account.
      for (let page = 1; page <= 10 && !userId; page++) {
        const { data: list } = await admin.auth.admin.listUsers({
          page,
          perPage: 200,
        });
        const hit = list?.users.find(
          (u) => u.email?.toLowerCase() === email.toLowerCase(),
        );
        if (hit) userId = hit.id;
        if (!list || list.users.length < 200) break;
      }
      if (!userId) throw new Error(inviteError.message);
    }
    if (!userId) throw new Error("Could not resolve the invited user.");

    // Membership insert runs under the CALLER's JWT so RLS re-verifies that
    // they administer this org.
    const supabase = await createClient();
    const { error } = await supabase
      .from("memberships")
      .insert({ org_id: ctx.org.id, user_id: userId, role });
    if (error) {
      throw new Error(
        error.code === "23505" ? "That user is already a member." : error.message,
      );
    }
    revalidatePath("/settings");
    return { ok: true, message: `Invited ${email} as ${role}.` };
  } catch (e) {
    return fail(e);
  }
}

export async function updateMemberRole(
  userId: string,
  role: Role,
): Promise<ActionResult> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(ADMIN_ROLES);
    if (userId === ctx.user.id)
      return { ok: false, message: "You cannot change your own role." };
    const supabase = await createClient();
    const { error } = await supabase
      .from("memberships")
      .update({ role })
      .eq("org_id", ctx.org.id)
      .eq("user_id", userId);
    if (error) throw new Error(error.message);
    revalidatePath("/settings");
    return { ok: true };
  } catch (e) {
    return fail(e);
  }
}

export async function removeMember(userId: string): Promise<ActionResult> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(ADMIN_ROLES);
    if (userId === ctx.user.id)
      return { ok: false, message: "Leave the org from your own account menu instead." };
    const supabase = await createClient();
    const { error } = await supabase
      .from("memberships")
      .delete()
      .eq("org_id", ctx.org.id)
      .eq("user_id", userId);
    if (error) throw new Error(error.message);
    revalidatePath("/settings");
    return { ok: true, message: "Member removed." };
  } catch (e) {
    return fail(e);
  }
}

// ── API keys (Pro+ entitlement) ──────────────────────────────────────────────

export async function createApiKey(
  name: string,
): Promise<ActionResult<{ plaintext: string }>> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(ADMIN_ROLES);
    if (!ctx.quota.api_access) {
      return {
        ok: false,
        message: "API access is a Pro+ entitlement. Upgrade to create keys.",
      };
    }
    // Plaintext shown once; only the hash is stored (schema: api_keys.key_hash).
    const plaintext = `ack_live_${randomBytes(24).toString("hex")}`;
    const keyHash = createHash("sha256").update(plaintext).digest("hex");

    const supabase = await createClient();
    const { error } = await supabase.from("api_keys").insert({
      org_id: ctx.org.id,
      name: name.trim() || "Unnamed key",
      key_hash: keyHash,
      scopes: ["submit", "read"],
      created_by: ctx.user.id,
    });
    if (error) throw new Error(error.message);
    revalidatePath("/settings/api-keys");
    return { ok: true, data: { plaintext } };
  } catch (e) {
    return fail(e);
  }
}

export async function revokeApiKey(id: string): Promise<ActionResult> {
  if (isDemoMode) return DEMO_BLOCK;
  try {
    const ctx = await requireOrgRole(ADMIN_ROLES);
    const supabase = await createClient();
    const { error } = await supabase
      .from("api_keys")
      .update({ revoked_at: new Date().toISOString() })
      .eq("id", id)
      .eq("org_id", ctx.org.id);
    if (error) throw new Error(error.message);
    revalidatePath("/settings/api-keys");
    return { ok: true, message: "Key revoked." };
  } catch (e) {
    return fail(e);
  }
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export async function signOut(): Promise<void> {
  if (!isDemoMode) {
    const supabase = await createClient();
    await supabase.auth.signOut();
  }
  redirect("/login");
}
