"use client";

import { useState } from "react";
import { Copy, KeyRound, ShieldOff } from "lucide-react";
import { createApiKey, revokeApiKey } from "@/app/actions";
import type { ApiKey } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatDate, timeAgo } from "@/lib/utils";

export function ApiKeysPanel({
  keys,
  canManage,
}: {
  keys: ApiKey[];
  canManage: boolean;
}) {
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setPlaintext(null);
    const res = await createApiKey(name);
    setPending(false);
    if (!res.ok) {
      setError(res.message);
      return;
    }
    setPlaintext(res.data!.plaintext);
    setName("");
  }

  async function revoke(id: string, keyName: string) {
    if (!window.confirm(`Revoke "${keyName}"? Existing integrations will stop working.`))
      return;
    const res = await revokeApiKey(id);
    if (!res.ok) setError(res.message);
  }

  return (
    <div className="space-y-4">
      {canManage && (
        <Card>
          <CardHeader>
            <CardTitle>Create a key</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <form onSubmit={create} className="flex flex-wrap items-end gap-3">
              <div className="min-w-52 flex-1 space-y-1.5">
                <Label htmlFor="key-name">Key name</Label>
                <Input
                  id="key-name"
                  required
                  placeholder="CI pipeline"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <Button type="submit" disabled={pending}>
                <KeyRound size={14} /> {pending ? "Creating…" : "Create key"}
              </Button>
            </form>

            {plaintext && (
              <div className="rounded-xl border border-brand/30 bg-brand/5 p-4">
                <p className="text-xs font-medium text-brand">
                  Copy this key now — it will never be shown again.
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-lg bg-canvas px-3 py-2 font-mono text-[11px]">
                    {plaintext}
                  </code>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={async () => {
                      await navigator.clipboard.writeText(plaintext);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 2000);
                    }}
                  >
                    <Copy size={13} /> {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
              </div>
            )}

            {error && (
              <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {error}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="px-0 py-2">
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>Name</TH>
                <TH>Scopes</TH>
                <TH>Created</TH>
                <TH>Last used</TH>
                <TH>Status</TH>
                {canManage && <TH className="text-right">Actions</TH>}
              </TR>
            </THead>
            <TBody>
              {keys.length === 0 && (
                <TR>
                  <TD colSpan={6} className="py-10 text-center text-ink-faint">
                    No keys yet.
                  </TD>
                </TR>
              )}
              {keys.map((k) => (
                <TR key={k.id}>
                  <TD className="text-xs font-medium">{k.name}</TD>
                  <TD>
                    <div className="flex gap-1">
                      {k.scopes.map((s) => (
                        <Badge key={s} className="font-mono">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  </TD>
                  <TD className="text-xs text-ink-faint">{formatDate(k.created_at)}</TD>
                  <TD className="text-xs text-ink-faint">
                    {k.last_used_at ? timeAgo(k.last_used_at) : "never"}
                  </TD>
                  <TD>
                    {k.revoked_at ? (
                      <Badge className="border-rose-500/30 bg-rose-500/10 text-rose-300">
                        revoked
                      </Badge>
                    ) : (
                      <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
                        active
                      </Badge>
                    )}
                  </TD>
                  {canManage && (
                    <TD className="text-right">
                      {!k.revoked_at && (
                        <button
                          type="button"
                          onClick={() => revoke(k.id, k.name)}
                          title="Revoke key"
                          className="text-ink-faint transition-colors hover:text-rose-300"
                        >
                          <ShieldOff size={15} />
                        </button>
                      )}
                    </TD>
                  )}
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
