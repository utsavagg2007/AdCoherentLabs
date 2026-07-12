"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createOrg } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";

export function OnboardingForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    const result = await createOrg(name);
    if (!result.ok) {
      setError(result.message);
      setPending(false);
      return;
    }
    router.push("/dashboard");
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="mt-6 space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="org-name">Organization name</Label>
        <Input
          id="org-name"
          required
          minLength={2}
          placeholder="Acme Lending Inc."
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      {error && (
        <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      )}
      <Button type="submit" className="w-full" disabled={pending}>
        {pending ? "Creating…" : "Create organization"}
      </Button>
      <p className="text-[11px] leading-relaxed text-ink-faint">
        Starts on the Free tier (20 scans/month). Joining an existing org
        instead? Ask an admin to invite you from Settings → Members.
      </p>
    </form>
  );
}
