"use client";

import { useEffect, useRef, useState } from "react";
import { Building2, Check, ChevronsUpDown } from "lucide-react";
import { setActiveOrg } from "@/app/actions";
import { cn } from "@/lib/utils";
import type { OrgSummary } from "@/lib/types";

export function OrgSwitcher({
  org,
  orgs,
}: {
  org: OrgSummary;
  orgs: OrgSummary[];
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 rounded-xl border border-line bg-raised px-3 py-2.5 text-left transition-colors hover:border-line-bright"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand/10 text-brand">
          <Building2 size={14} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">
            {org.name}
          </span>
          <span className="block text-[10px] uppercase tracking-wider text-ink-faint">
            {org.role}
          </span>
        </span>
        <ChevronsUpDown size={14} className="shrink-0 text-ink-faint" />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-0 right-0 top-full z-50 mt-1.5 overflow-hidden rounded-xl border border-line-bright bg-overlay shadow-xl shadow-black/50"
        >
          {orgs.map((o) => (
            <button
              key={o.id}
              type="button"
              role="option"
              aria-selected={o.id === org.id}
              onClick={() => {
                setOpen(false);
                if (o.id !== org.id) void setActiveOrg(o.id);
              }}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-2.5 text-left text-[13px] transition-colors hover:bg-raised",
                o.id === org.id ? "text-brand" : "text-ink-dim",
              )}
            >
              <span className="min-w-0 flex-1 truncate">{o.name}</span>
              {o.id === org.id && <Check size={13} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
