import Image from "next/image";
import { cn } from "@/lib/utils";

/** Brand lockup: the faceted-chrome mark + wordmark. The mark image carries
 * its own dark metal field, so it sits in a rounded tile on every surface.
 * `tone` is kept for call-site compatibility — the theme is dark-first, so
 * both tones resolve to chrome text. */
export function Logo({
  tone = "light",
  className,
  compact,
}: {
  tone?: "light" | "dark";
  className?: string;
  compact?: boolean;
}) {
  void tone;
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <Image
        src="/brand/logo-mark-96.png"
        alt=""
        aria-hidden
        width={28}
        height={28}
        className="size-7 shrink-0 rounded-[8px] ring-1 ring-white/15"
        priority
      />
      {!compact && (
        <span className="font-display text-[17px] leading-none font-bold tracking-tight text-ink-900">
          AdCoherent{" "}
          <span className="font-medium text-ink-600">Labs</span>
        </span>
      )}
    </span>
  );
}
