/** Empty-state artwork.
 *
 * `SubmissionsArt` is a rendered still; the other two are drawn here as SVG.
 * Both routes end up in the same place visually because the render is masked
 * to a soft circle, so its studio background dissolves into whichever theme
 * is showing instead of sitting on the page as a grey tile.
 *
 * The drawn ones reference theme tokens directly, so they recolor with the
 * theme rather than needing a second file. */

import Image from "next/image";
import { cn } from "@/lib/utils";

const MASK =
  "radial-gradient(circle at 50% 48%, #000 46%, rgb(0 0 0 / 0.55) 62%, transparent 74%)";

export function SubmissionsArt({ className }: { className?: string }) {
  return (
    <div className={cn("relative size-36", className)} aria-hidden>
      <Image
        src="/media/empty-submissions.png"
        alt=""
        fill
        sizes="144px"
        className="object-contain"
        style={{ maskImage: MASK, WebkitMaskImage: MASK }}
      />
    </div>
  );
}

/** A report sheet with a verification seal — the counterpart to the render,
 * drawn so it costs nothing and recolors with the theme. */
export function ReportsArt({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 144 144"
      fill="none"
      aria-hidden
      className={cn("size-36", className)}
    >
      <defs>
        <linearGradient id="rep-sheet" x1="44" y1="26" x2="104" y2="118" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--brand)" stopOpacity="0.22" />
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0.12" />
        </linearGradient>
      </defs>

      <ellipse cx="72" cy="124" rx="34" ry="5" fill="var(--tint-2)" />

      {/* two sheets behind, fanned */}
      <rect x="40" y="30" width="60" height="80" rx="8" fill="var(--tint-2)"
        transform="rotate(-8 70 70)" />
      <rect x="46" y="26" width="60" height="80" rx="8" fill="var(--tint-1)"
        stroke="var(--line)" transform="rotate(-3 76 66)" />

      {/* the front sheet */}
      <rect x="44" y="24" width="60" height="82" rx="9"
        fill="url(#rep-sheet)" stroke="var(--brand-soft-line)" />
      {[38, 48, 58, 68].map((y, i) => (
        <rect key={y} x="54" y={y} width={i === 3 ? 24 : 40} height="4" rx="2"
          fill="var(--text-faint)" opacity={0.45} />
      ))}

      {/* the seal */}
      <circle cx="98" cy="92" r="17" fill="var(--surface)" stroke="var(--pass-line)" strokeWidth="1.5" />
      <circle cx="98" cy="92" r="17" fill="var(--pass-soft)" />
      <path d="m91 92 5 5 10-11" stroke="var(--pass-fg)" strokeWidth="2.6"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Stacked credit discs behind a meter arc — the ledger's empty state. */
export function CreditsArt({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 144 144"
      fill="none"
      aria-hidden
      className={cn("size-36", className)}
    >
      <defs>
        <linearGradient id="cr-disc" x1="40" y1="60" x2="104" y2="104" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--brand)" stopOpacity="0.55" />
          <stop offset="1" stopColor="var(--indigo-500)" stopOpacity="0.3" />
        </linearGradient>
      </defs>

      {/* the meter arc, opening upward, drawn as the gauge behind the stack */}
      <path d="M30 96a42 42 0 0 1 84 0" stroke="var(--line-strong)" strokeWidth="3"
        strokeLinecap="round" />
      <path d="M30 96a42 42 0 0 1 26-38.8" stroke="var(--accent)" strokeWidth="3"
        strokeLinecap="round" />

      {/* three discs, stacked with a visible edge on each */}
      {[0, 1, 2].map((i) => {
        const y = 104 - i * 13;
        return (
          <g key={i}>
            <ellipse cx="72" cy={y} rx="30" ry="11" fill="var(--tint-3)" />
            <ellipse cx="72" cy={y - 3} rx="30" ry="11" fill="url(#cr-disc)"
              stroke="var(--brand-soft-line)" />
          </g>
        );
      })}
      <ellipse cx="72" cy="75" rx="14" ry="5" fill="var(--surface)" opacity="0.5" />
    </svg>
  );
}
