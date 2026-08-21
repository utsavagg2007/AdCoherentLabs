"use client";

/** Workspace + team settings. Member management is admin+, may require a
 * recent MFA challenge (step_up_required), and only attaches people who
 * already have accounts — this backend does not send email invitations. */

import { useState } from "react";
import { ShieldAlert, Trash2, UserPlus, Users } from "lucide-react";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { useApi, useAuth, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ErrorPanel, Skeleton } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { describeError, isApiError } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import type { MemberRow, Role } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const ROLE_HELP: { role: Role; text: string }[] = [
  { role: "owner", text: "Full control, cannot be removed or reassigned here." },
  { role: "admin", text: "Manages members, billing, and API keys; can review." },
  { role: "reviewer", text: "Runs analyses and works the findings queue." },
  { role: "viewer", text: "Read-only: reports, history, and dashboards." },
];

const ROLE_BADGE: Record<Role, string> = {
  owner: "border-line-strong bg-tint text-body",
  admin: "border-live-line bg-live-soft text-live",
  reviewer: "border-pass-line bg-pass-soft text-pass",
  viewer: "border-line bg-tint text-muted",
};

export default function SettingsPage() {
  const api = useApi();
  const { session } = useAuth();
  const { orgId, orgName, role } = useOrg();
  const { toast } = useToast();

  const orgMe = useAsyncData((s) => api.orgMe(s), [api, orgId]);
  const members = useAsyncData((s) => api.listMembers(s), [api, orgId]);

  const [addEmail, setAddEmail] = useState("");
  const [addRole, setAddRole] = useState<Exclude<Role, "owner">>("reviewer");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<unknown>(null);
  const [removing, setRemoving] = useState<MemberRow | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [roleBusy, setRoleBusy] = useState<string | null>(null);

  const isAdmin = role === "admin" || role === "owner";
  const stepUp = (e: unknown) => isApiError(e) && e.code === "step_up_required";

  async function addMember(e: React.FormEvent) {
    e.preventDefault();
    setAdding(true);
    setAddError(null);
    try {
      await api.addMember(addEmail.trim(), addRole);
      setAddEmail("");
      members.refresh({ silent: true });
      toast({ kind: "success", title: "Member added" });
    } catch (err) {
      setAddError(err);
    } finally {
      setAdding(false);
    }
  }

  async function changeRole(m: MemberRow, newRole: Exclude<Role, "owner">) {
    setRoleBusy(m.user_id);
    try {
      await api.changeMemberRole(m.user_id, newRole);
      members.refresh({ silent: true });
      toast({ kind: "success", title: `${m.email} is now ${newRole}` });
    } catch (err) {
      const d = describeError(err);
      toast({ kind: "error", title: d.title, detail: d.detail });
    } finally {
      setRoleBusy(null);
    }
  }

  async function removeMember() {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await api.removeMember(removing.user_id);
      toast({ kind: "success", title: `${removing.email} removed` });
      setRemoving(null);
      members.refresh({ silent: true });
    } catch (err) {
      const d = describeError(err);
      toast({ kind: "error", title: d.title, detail: d.detail });
    } finally {
      setRemoveBusy(false);
    }
  }

  const seatCount = members.data?.members.length ?? 0;
  const seats = members.data?.seats ?? orgMe.data?.entitlements.seats ?? null;

  return (
    <>
      <PageHeader
        title="Settings"
        description="Workspace profile and team access."
      />
      <PageBody>
        <div className="max-w-3xl space-y-8">
          {/* workspace */}
          <section aria-label="Workspace" className="card p-5">
            <h2 className="text-[13px] font-extrabold tracking-wide text-strong uppercase">
              Workspace
            </h2>
            {orgMe.loading ? (
              <Skeleton className="mt-3 h-14" />
            ) : (
              <dl className="mt-3 grid gap-x-6 gap-y-3 text-[13.5px] sm:grid-cols-3">
                <div>
                  <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                    Name
                  </dt>
                  <dd className="mt-0.5 font-bold text-strong">{orgName}</dd>
                </div>
                <div>
                  <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                    Plan
                  </dt>
                  <dd className="mt-0.5 font-bold text-strong capitalize">
                    {orgMe.data?.tier}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                    Created
                  </dt>
                  <dd className="mt-0.5 font-bold text-strong">
                    {formatDate(orgMe.data?.org.created_at)}
                  </dd>
                </div>
              </dl>
            )}
            <p className="mt-3 text-[12px] text-subtle">
              Your role here: <span className="font-bold capitalize">{role}</span>
              {session?.user.email ? ` · signed in as ${session.user.email}` : ""}
            </p>
          </section>

          {/* roles explainer */}
          <section aria-label="Roles" className="card p-5">
            <h2 className="flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-strong uppercase">
              <Users className="size-4 text-muted" aria-hidden />
              Roles
            </h2>
            <ul className="mt-3 grid gap-2.5 sm:grid-cols-2">
              {ROLE_HELP.map((r) => (
                <li key={r.role} className="rounded-xl bg-surface p-3">
                  <Badge className={ROLE_BADGE[r.role]}>{r.role}</Badge>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    {r.text}
                  </p>
                </li>
              ))}
            </ul>
          </section>

          {/* team */}
          <section aria-label="Team">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-[13px] font-extrabold tracking-wide text-strong uppercase">
                Team
              </h2>
              <p className="text-[12px] text-subtle tabular-nums">
                {seatCount}
                {seats != null ? ` / ${seats}` : ""} seats used
              </p>
            </div>

            {members.error ? (
              <ErrorPanel error={members.error} onRetry={() => members.refresh()} />
            ) : members.loading ? (
              <Skeleton className="h-32" />
            ) : (
              <div className="card divide-y divide-line">
                {members.data!.members.map((m) => {
                  const isSelf = m.user_id === session?.user.id;
                  const canEdit = isAdmin && m.role !== "owner" && !isSelf;
                  return (
                    <div key={m.user_id} className="flex items-center gap-3 px-4 py-3">
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface text-[12px] font-extrabold text-white">
                        {m.email.slice(0, 1).toUpperCase()}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13.5px] font-bold text-strong">
                          {m.email}
                          {isSelf && (
                            <span className="ml-1.5 text-[11px] font-semibold text-subtle">
                              (you)
                            </span>
                          )}
                        </span>
                        <span className="block text-[11.5px] text-subtle">
                          Since {formatDate(m.created_at)}
                        </span>
                      </span>
                      {canEdit ? (
                        <>
                          <label className="sr-only" htmlFor={`role-${m.user_id}`}>
                            Role for {m.email}
                          </label>
                          <select
                            id={`role-${m.user_id}`}
                            className="input !w-auto !py-1.5 text-[12.5px]"
                            value={m.role}
                            disabled={roleBusy === m.user_id}
                            onChange={(e) =>
                              changeRole(m, e.target.value as Exclude<Role, "owner">)
                            }
                          >
                            <option value="admin">admin</option>
                            <option value="reviewer">reviewer</option>
                            <option value="viewer">viewer</option>
                          </select>
                          <button
                            type="button"
                            onClick={() => setRemoving(m)}
                            aria-label={`Remove ${m.email}`}
                            className="rounded-lg p-2 text-subtle hover:bg-fail-soft hover:text-fail"
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </>
                      ) : (
                        <Badge className={ROLE_BADGE[m.role]}>{m.role}</Badge>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* add member */}
            {isAdmin && (
              <form onSubmit={addMember} className="card mt-4 p-4">
                <h3 className="flex items-center gap-2 text-[12.5px] font-extrabold tracking-wide text-strong uppercase">
                  <UserPlus className="size-4 text-muted" aria-hidden />
                  Add a member
                </h3>
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-subtle">
                  They need an AdCoherent account already — no invitation email
                  is sent. Ask them to sign up first, then add their address
                  here.
                </p>
                <div className="mt-3 flex flex-wrap gap-2.5">
                  <input
                    type="email"
                    required
                    className="input min-w-52 flex-1"
                    placeholder="teammate@company.com"
                    value={addEmail}
                    onChange={(e) => setAddEmail(e.target.value)}
                    aria-label="Member email"
                  />
                  <select
                    className="input !w-auto"
                    value={addRole}
                    onChange={(e) =>
                      setAddRole(e.target.value as Exclude<Role, "owner">)
                    }
                    aria-label="Member role"
                  >
                    <option value="admin">admin</option>
                    <option value="reviewer">reviewer</option>
                    <option value="viewer">viewer</option>
                  </select>
                  <Button type="submit" loading={adding} disabled={!addEmail.trim()}>
                    Add member
                  </Button>
                </div>
                {addError != null && (
                  <div
                    role="alert"
                    className="mt-3 flex items-start gap-2.5 rounded-xl border border-warn-line bg-warn-soft p-3.5 text-[13px] leading-relaxed text-warn"
                  >
                    <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                    <div>
                      {stepUp(addError) ? (
                        <>
                          <p className="font-bold">
                            Re-authentication required first
                          </p>
                          <p className="mt-0.5">
                            Your account has MFA enabled, and membership changes
                            need a recent second-factor challenge. Sign out,
                            sign back in with your authenticator code, then
                            retry.
                          </p>
                        </>
                      ) : isApiError(addError) && addError.status === 404 ? (
                        <>
                          <p className="font-bold">No account with that email</p>
                          <p className="mt-0.5">
                            This platform doesn&apos;t send invitations — ask
                            them to create an account at the signup page, then
                            add them again.
                          </p>
                        </>
                      ) : (
                        <p>{describeError(addError).detail}</p>
                      )}
                    </div>
                  </div>
                )}
              </form>
            )}
          </section>
        </div>
      </PageBody>

      {/* remove confirmation */}
      <Dialog
        open={removing !== null}
        onOpenChange={(o) => !o && !removeBusy && setRemoving(null)}
      >
        <DialogContent
          title="Remove this member?"
          description={
            removing
              ? `${removing.email} will immediately lose access to ${orgName}. Their past reviews and audit records stay intact.`
              : undefined
          }
        >
          <div className="flex justify-end gap-2.5">
            <Button
              variant="secondary"
              onClick={() => setRemoving(null)}
              disabled={removeBusy}
            >
              Cancel
            </Button>
            <Button variant="danger" onClick={removeMember} loading={removeBusy}>
              Remove member
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
