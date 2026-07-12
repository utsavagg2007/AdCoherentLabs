import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-lg bg-brand/15 text-brand",
        className,
      )}
      aria-hidden
    >
      {/* Four stacked layers — the engine */}
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
        <path
          d="M12 3 21 7.5 12 12 3 7.5 12 3Z"
          fill="currentColor"
          fillOpacity="0.9"
        />
        <path
          d="M3 12.25 12 16.75 21 12.25"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M3 16.75 12 21.25 21 16.75"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeOpacity="0.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">
        AdCoherent<span className="text-brand"> Labs</span>
      </span>
    </span>
  );
}
