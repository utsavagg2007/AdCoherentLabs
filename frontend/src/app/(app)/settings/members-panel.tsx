"use client";

import { useState } from "react";
import { UserPlus, UserX } from "lucide-react";
import { inviteMember, removeMember, updateMemberRole } from "@/app/actions";
import type { MemberRow } from "@/lib/data";
import type { Role } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatDate } from "@/lib/utils";

const ROLES: Role[] = ["admin", "reviewer", "viewer"];

const ROLE_HINT: Record<Role, string> = {
  owner: "Everything, incl. billing & members",
  admin: "Members, settings, reviews",
  reviewer: "Submit, run, approve findings",
  viewer: "Read reports only",
};

export function MembersPanel({
  members,
  selfId,
  canManage,
}: {
  members: MemberRow[];
  selfId: string;
  canManage: boolean;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("reviewer");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setMessage(null);
    const res = await inviteMember(email, role);
    setPending(false);
    setMessage({ ok: res.ok, text: res.ok ? (res.message ?? "Invited.") : res.message });
    if (res.ok) setEmail("");
  }

  async function changeRole(userId: string, newRole: Role) {
    setMessage(null);
    const res = await updateMemberRole(userId, newRole);
    if (!res.ok) setMessage({ ok: false, text: res.message });
  }

  async function remove(userId: string, memberEmail: string) {
    if (!window.confirm(`Remove ${memberEmail} from the organization?`)) return;
    const res = await removeMember(userId);
    setMessage({ ok: res.ok, text: res.ok ? "Member removed." : res.message });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members & roles</CardTitle>
        <CardDescription>
          Role controls what a user may do; the org&apos;s plan controls what is
          unlocked — two independent axes (playbook Phase 3).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {canManage && (
          <form
            onSubmit={invite}
            className="flex flex-wrap items-end gap-3 rounded-xl border border-line bg-raised/40 p-4"
          >
            <div className="min-w-52 flex-1 space-y-1.5">
              <Label htmlFor="invite-email">Invite by work email</Label>
              <Input
                id="invite-email"
                type="email"
                required
                placeholder="teammate@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invite-role">Role</Label>
              <Select
                id="invite-role"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r} — {ROLE_HINT[r]}
                  </option>
                ))}
              </Select>
            </div>
            <Button type="submit" size="md" disabled={pending}>
              <UserPlus size={14} /> {pending ? "Inviting…" : "Invite"}
            </Button>
          </form>
        )}

        {message && (
          <p
            className={
              message.ok
                ? "text-xs text-brand"
                : "rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300"
            }
          >
            {message.text}
          </p>
        )}

        <Table>
          <THead>
            <TR className="hover:bg-transparent">
              <TH>Member</TH>
              <TH>Role</TH>
              <TH>Joined</TH>
              {canManage && <TH className="text-right">Actions</TH>}
            </TR>
          </THead>
          <TBody>
            {members.map((m) => {
              const isSelf = m.user_id === selfId;
              const isOwner = m.role === "owner";
              return (
                <TR key={m.user_id}>
                  <TD>
                    <span className="text-xs font-medium">{m.email}</span>
                    {isSelf && (
                      <Badge className="ml-2 border-brand/30 bg-brand/10 text-brand">
                        you
                      </Badge>
                    )}
                  </TD>
                  <TD>
                    {canManage && !isOwner && !isSelf ? (
                      <Select
                        className="h-8 text-xs"
                        value={m.role}
                        onChange={(e) =>
                          changeRole(m.user_id, e.target.value as Role)
                        }
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Badge className="capitalize">{m.role}</Badge>
                    )}
                  </TD>
                  <TD className="text-xs text-ink-faint">
                    {formatDate(m.created_at)}
                  </TD>
                  {canManage && (
                    <TD className="text-right">
                      {!isOwner && !isSelf && (
                        <button
                          type="button"
                          onClick={() => remove(m.user_id, m.email)}
                          title="Remove member"
                          className="text-ink-faint transition-colors hover:text-rose-300"
                        >
                          <UserX size={15} />
                        </button>
                      )}
                    </TD>
                  )}
                </TR>
              );
            })}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}
