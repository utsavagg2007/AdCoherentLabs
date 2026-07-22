"use client";

import { useMemo, useState } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Check, ChevronsUpDown, MapPin, X } from "lucide-react";
import { US_JURISDICTIONS } from "@/lib/jurisdictions";
import { cn } from "@/lib/utils";

export function JurisdictionSelect({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (codes: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return US_JURISDICTIONS;
    return US_JURISDICTIONS.filter(
      (j) =>
        j.name.toLowerCase().includes(q) || j.code.toLowerCase().includes(q)
    );
  }, [query]);

  const toggle = (code: string) => {
    onChange(
      selected.includes(code)
        ? selected.filter((c) => c !== code)
        : [...selected, code]
    );
  };

  return (
    <div>
      <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
        <PopoverPrimitive.Trigger
          className="input flex items-center justify-between gap-2 text-left"
          aria-label="Target jurisdictions"
        >
          <span className="flex min-w-0 items-center gap-2">
            <MapPin className="size-4 shrink-0 text-ink-500" aria-hidden />
            <span
              className={cn(
                "truncate",
                selected.length === 0 && "text-ink-500"
              )}
            >
              {selected.length === 0
                ? "Nationwide (no state targeting)"
                : `${selected.length} state${selected.length > 1 ? "s" : ""} targeted`}
            </span>
          </span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-ink-500" aria-hidden />
        </PopoverPrimitive.Trigger>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            align="start"
            sideOffset={6}
            className="z-50 w-[300px] rounded-xl border border-line bg-coal-800 shadow-(--shadow-float)"
          >
            <div className="border-b border-line p-2">
              <input
                className="input !py-2 text-[13px]"
                placeholder="Search states…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search states"
              />
            </div>
            <ul className="max-h-64 overflow-y-auto p-1.5" role="listbox" aria-multiselectable>
              {filtered.map((j) => {
                const on = selected.includes(j.code);
                return (
                  <li key={j.code}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={on}
                      onClick={() => toggle(j.code)}
                      className={cn(
                        "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium",
                        on
                          ? "bg-white/6 text-ink-950"
                          : "text-ink-800 hover:bg-cream"
                      )}
                    >
                      <span
                        className={cn(
                          "flex size-4 items-center justify-center rounded border",
                          on
                            ? "border-white/70 bg-white/90 text-coal-950"
                            : "border-white/15 bg-coal-800"
                        )}
                        aria-hidden
                      >
                        {on && <Check className="size-3" />}
                      </span>
                      <span className="flex-1">{j.name}</span>
                      <span className="font-mono text-[11px] text-ink-500">
                        {j.code}
                      </span>
                    </button>
                  </li>
                );
              })}
              {filtered.length === 0 && (
                <li className="px-3 py-4 text-center text-[12.5px] text-ink-500">
                  No matching state.
                </li>
              )}
            </ul>
            {selected.length > 0 && (
              <div className="border-t border-line p-2">
                <button
                  type="button"
                  onClick={() => onChange([])}
                  className="w-full rounded-lg px-2 py-1.5 text-[12.5px] font-semibold text-ink-500 hover:bg-cream hover:text-ink-900"
                >
                  Clear selection
                </button>
              </div>
            )}
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>

      {selected.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Selected jurisdictions">
          {selected.map((code) => {
            const j = US_JURISDICTIONS.find((x) => x.code === code);
            return (
              <li key={code}>
                <span className="inline-flex items-center gap-1 rounded-full border border-white/15 bg-white/6 py-0.5 pr-1 pl-2.5 text-[11.5px] font-bold text-ink-850">
                  {j?.name ?? code}
                  <button
                    type="button"
                    onClick={() => toggle(code)}
                    aria-label={`Remove ${j?.name ?? code}`}
                    className="rounded-full p-0.5 hover:bg-violet-200"
                  >
                    <X className="size-3" />
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-2 text-[11.5px] leading-relaxed text-ink-500">
        State targeting adds state UDAP coverage alongside federal frameworks.
      </p>
    </div>
  );
}
