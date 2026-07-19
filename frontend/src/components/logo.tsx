import { cn } from "@/lib/utils";

/** Wordmark. `tone` controls text color for dark/light surfaces. */
export function Logo({
  tone = "light",
  className,
  compact,
}: {
  tone?: "light" | "dark";
  className?: string;
  compact?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg
        viewBox="0 0 28 28"
        aria-hidden
        className="size-7 shrink-0"
        fill="none"
      >
        <rect x="2" y="2" width="24" height="24" rx="7" fill="#7c3aed" />
        <path
          d="M8 17.5 12.2 8.5a1 1 0 0 1 1.8 0l1.6 3.4"
          stroke="white"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="m13.5 15.5 2 2.5 4.5-6"
          stroke="#c4b5fd"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {!compact && (
        <span
          className={cn(
            "text-[17px] leading-none font-extrabold tracking-tight",
            tone === "light" ? "text-white" : "text-ink-900"
          )}
        >
          AdCoherent{" "}
          <span
            className={cn(
              "font-medium",
              tone === "light" ? "text-white/60" : "text-zinc-400"
            )}
          >
            Labs
          </span>
        </span>
      )}
    </span>
  );
}
