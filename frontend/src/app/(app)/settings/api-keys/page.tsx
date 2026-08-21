"use client";

/** API keys — admin-only, plans with api_access. The plaintext secret is
 * shown exactly once in a deliberate copy-and-confirm dialog and never again.
 */

import { useState } from "react";
import {
  Check,
  Copy,
  KeyRound,
  Lock,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { useApi, useOrg } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { EmptyState, ErrorPanel, Skeleton } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { describeError, isApiError } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import type { ApiKeyCreated, ApiKeyRow } from "@/lib/types";
import { formatDate, timeAgo } from "@/lib/utils";

const SCOPES = [
  { id: "read", label: "read", help: "List and fetch runs, reports, findings." },
  { id: "submit", label: "submit", help: "Create submissions and resume runs." },
  { id: "admin", label: "admin", help: "Org administration — grant sparingly." },
];

export default function ApiKeysPage() {
  const api = useApi();
  const { orgId, role } = useOrg();
  const { toast } = useToast();

  const orgMe = useAsyncData((s) => api.orgMe(s), [api, orgId]);
  const keys = useAsyncData((s) => api.listApiKeys(s), [api, orgId]);

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read", "submit"]);
  const [rpm, setRpm] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmedStored, setConfirmedStored] = useState(false);
  const [revoking, setRevoking] = useState<ApiKeyRow | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);

  const isAdmin = role === "admin" || role === "owner";
  const hasApiAccess = Boolean(orgMe.data?.entitlements.api_access);

  async function createKey(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || scopes.length === 0) return;
    setCreating(true);
    setCreateError(null);
    try {
      const rpmNum = rpm.trim() ? parseInt(rpm, 10) : null;
      const res = await api.createApiKey({
        name: name.trim(),
        scopes,
        rate_limit_rpm: rpmNum && rpmNum > 0 ? rpmNum : null,
      });
      setCreated(res);
      setCopied(false);
      setConfirmedStored(false);
      setCreateOpen(false);
      setName("");
      setRpm("");
      setScopes(["read", "submit"]);
      keys.refresh({ silent: true });
    } catch (err) {
      setCreateError(err);
    } finally {
      setCreating(false);
    }
  }

  async function copySecret() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.api_key);
      setCopied(true);
    } catch {
      toast({
        kind: "error",
        title: "Clipboard unavailable",
        detail: "Select the key text and copy it manually.",
      });
    }
  }

  async function revoke() {
    if (!revoking) return;
    setRevokeBusy(true);
    try {
      await api.revokeApiKey(revoking.id);
      toast({ kind: "success", title: `“${revoking.name}” revoked` });
      setRevoking(null);
      keys.refresh({ silent: true });
    } catch (err) {
      const d = describeError(err);
      toast({ kind: "error", title: d.title, detail: d.detail });
    } finally {
      setRevokeBusy(false);
    }
  }

  // ---- gates ----
  if (!orgMe.loading && !isAdmin) {
    return (
      <>
        <PageHeader title="API keys" />
        <PageBody>
          <EmptyState
            icon={<Lock className="size-5" aria-hidden />}
            title="Admins only"
            description="API keys are workspace credentials — an admin or owner manages them."
          />
        </PageBody>
      </>
    );
  }
  if (!orgMe.loading && isAdmin && !hasApiAccess) {
    return (
      <>
        <PageHeader title="API keys" />
        <PageBody>
          <EmptyState
            icon={<KeyRound className="size-5" aria-hidden />}
            title="API access starts on the Pro plan"
            description={`The ${orgMe.data?.tier} plan doesn't include programmatic access. Upgrade to Pro or Design to mint scoped keys.`}
            action={
              <Button href="/billing" variant="secondary">
                View plans
              </Button>
            }
          />
        </PageBody>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="API keys"
        description="Scoped credentials for programmatic submissions. Requests authenticate with the X-API-Key header."
        actions={
          <Button onClick={() => setCreateOpen(true)} disabled={orgMe.loading}>
            <KeyRound className="size-4" aria-hidden />
            Create key
          </Button>
        }
      />
      <PageBody>
        {keys.error ? (
          <ErrorPanel error={keys.error} onRetry={() => keys.refresh()} />
        ) : keys.loading || orgMe.loading ? (
          <Skeleton className="h-40" />
        ) : keys.data!.api_keys.length === 0 ? (
          <EmptyState
            icon={<KeyRound className="size-5" aria-hidden />}
            title="No API keys yet"
            description="Mint a key with only the scopes your integration needs. The secret is shown once."
            action={<Button onClick={() => setCreateOpen(true)}>Create your first key</Button>}
          />
        ) : (
          <div className="card max-w-4xl divide-y divide-line">
            {keys.data!.api_keys.map((k) => {
              const revoked = Boolean(k.revoked_at);
              return (
                <div key={k.id} className="flex items-center gap-4 px-4 py-3.5">
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-[14px] font-bold text-strong">
                        {k.name}
                      </span>
                      {revoked && (
                        <Badge className="border-fail-line bg-fail-soft text-fail">
                          Revoked {formatDate(k.revoked_at)}
                        </Badge>
                      )}
                    </span>
                    <span className="mt-0.5 block text-[11.5px] text-subtle">
                      Created {formatDate(k.created_at)} · last used{" "}
                      {k.last_used_at ? timeAgo(k.last_used_at) : "never"}
                      {k.rate_limit_rpm ? ` · ${k.rate_limit_rpm} rpm cap` : ""}
                    </span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    {(k.scopes ?? []).map((s) => (
                      <Badge
                        key={s}
                        className="border-line-strong bg-tint font-mono text-body"
                      >
                        {s}
                      </Badge>
                    ))}
                  </span>
                  {!revoked && (
                    <button
                      type="button"
                      onClick={() => setRevoking(k)}
                      aria-label={`Revoke ${k.name}`}
                      className="rounded-lg p-2 text-subtle hover:bg-fail-soft hover:text-fail"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </PageBody>

      {/* create dialog */}
      <Dialog open={createOpen} onOpenChange={(o) => !creating && setCreateOpen(o)}>
        <DialogContent
          title="Create an API key"
          description="Grant only the scopes this integration needs."
        >
          <form onSubmit={createKey} className="space-y-4">
            <div>
              <label htmlFor="key-name" className="label">
                Name
              </label>
              <input
                id="key-name"
                className="input"
                required
                maxLength={120}
                placeholder="ci-pipeline"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <fieldset>
              <legend className="label">Scopes</legend>
              <div className="space-y-2">
                {SCOPES.map((s) => {
                  const on = scopes.includes(s.id);
                  return (
                    <label
                      key={s.id}
                      className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-line p-3 hover:bg-hover"
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() =>
                          setScopes((prev) =>
                            on ? prev.filter((x) => x !== s.id) : [...prev, s.id]
                          )
                        }
                        className="mt-0.5 size-4 accent-violet-600"
                      />
                      <span>
                        <span className="font-mono text-[13px] font-bold text-strong">
                          {s.label}
                        </span>
                        <span className="block text-[12px] text-subtle">
                          {s.help}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
            <div>
              <label htmlFor="key-rpm" className="label">
                Rate limit{" "}
                <span className="font-normal text-subtle">
                  (requests/minute, optional)
                </span>
              </label>
              <input
                id="key-rpm"
                className="input"
                type="number"
                min={1}
                max={100000}
                placeholder={`Defaults to your plan cap${orgMe.data?.entitlements.api_rpm ? ` (${orgMe.data.entitlements.api_rpm} rpm)` : ""}`}
                value={rpm}
                onChange={(e) => setRpm(e.target.value)}
              />
            </div>
            {createError != null && (
              <div
                role="alert"
                className="flex items-start gap-2.5 rounded-xl border border-warn-line bg-warn-soft p-3.5 text-[13px] leading-relaxed text-warn"
              >
                <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <p>
                  {isApiError(createError) && createError.code === "step_up_required"
                    ? "Minting credentials requires a recent MFA challenge. Sign in again with your second factor, then retry."
                    : describeError(createError).detail}
                </p>
              </div>
            )}
            <div className="flex justify-end gap-2.5">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setCreateOpen(false)}
                disabled={creating}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                loading={creating}
                disabled={!name.trim() || scopes.length === 0}
              >
                Create key
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* reveal-once dialog */}
      <Dialog
        open={created !== null}
        onOpenChange={(o) => {
          if (!o && confirmedStored) setCreated(null);
        }}
      >
        <DialogContent
          title="Store this key now"
          description="This is the only time the secret is shown. It cannot be recovered later."
          hideClose
        >
          {created && (
            <div className="space-y-4">
              <div className="rounded-xl border border-line-strong bg-tint p-3.5">
                <p className="text-[11px] font-bold tracking-wider text-strong uppercase">
                  {created.prefix ? `Key · prefix ${created.prefix}` : "API key"}
                </p>
                <code className="mt-1.5 block font-mono text-[12.5px] break-all text-strong select-all">
                  {created.api_key}
                </code>
              </div>
              <div className="flex items-center gap-2.5">
                <Button variant="secondary" onClick={copySecret}>
                  {copied ? (
                    <Check className="size-4 text-pass" aria-hidden />
                  ) : (
                    <Copy className="size-4" aria-hidden />
                  )}
                  {copied ? "Copied" : "Copy key"}
                </Button>
                <p className="text-[12px] text-subtle">
                  Send it with the <code className="font-mono">X-API-Key</code>{" "}
                  header.
                </p>
              </div>
              <label className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-line p-3">
                <input
                  type="checkbox"
                  checked={confirmedStored}
                  onChange={(e) => setConfirmedStored(e.target.checked)}
                  className="mt-0.5 size-4 accent-violet-600"
                />
                <span className="text-[13px] leading-relaxed text-muted">
                  I&apos;ve stored this key somewhere safe and understand it
                  won&apos;t be shown again.
                </span>
              </label>
              <div className="flex justify-end">
                <Button disabled={!confirmedStored} onClick={() => setCreated(null)}>
                  Done
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* revoke dialog */}
      <Dialog
        open={revoking !== null}
        onOpenChange={(o) => !o && !revokeBusy && setRevoking(null)}
      >
        <DialogContent
          title="Revoke this API key?"
          description={
            revoking
              ? `“${revoking.name}” stops working immediately. Any integration using it will start receiving 401s. This cannot be undone.`
              : undefined
          }
        >
          <div className="flex justify-end gap-2.5">
            <Button
              variant="secondary"
              onClick={() => setRevoking(null)}
              disabled={revokeBusy}
            >
              Keep key
            </Button>
            <Button variant="danger" onClick={revoke} loading={revokeBusy}>
              Revoke permanently
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
