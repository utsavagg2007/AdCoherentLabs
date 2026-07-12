"use client";

import { useState } from "react";
import { updateOrgName } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function OrgSettingsForm({
  orgName,
  canEdit,
}: {
  orgName: string;
  canEdit: boolean;
}) {
  const [name, setName] = useState(orgName);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setMessage(null);
    const res = await updateOrgName(name);
    setPending(false);
    setMessage({ ok: res.ok, text: res.ok ? "Saved." : res.message });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Organization</CardTitle>
        <CardDescription>
          The tenant everything belongs to. Renaming is owner/admin only.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="org-name">Name</Label>
            <Input
              id="org-name"
              value={name}
              disabled={!canEdit}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
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
          {canEdit && (
            <Button
              type="submit"
              size="sm"
              disabled={pending || name.trim() === orgName}
            >
              {pending ? "Saving…" : "Save changes"}
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
