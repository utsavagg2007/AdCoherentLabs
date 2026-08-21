import { cn } from "@/lib/utils";

/** The brand mark, drawn rather than photographed.
 *
 * This used to be a 512px PNG scaled down to 28px inside a ring — which is
 * where most of the "pixelated" feel came from: a raster mark resampled at a
 * non-integer ratio, on every surface, at every zoom level, on every DPI.
 * As geometry it is exact at any size, weighs ~1KB inline instead of 170KB
 * over the network, and picks up the theme instead of carrying its own baked
 * dark tile that fought every light surface it landed on.
 *
 * The geometry is the same idea as the original: a faceted triangular "A"
 * with a camera aperture at its heart — evidence (the lens) inside judgment
 * (the letter). */

/* Fixed gradient ids, not generated ones. Every mark on the page defines the
   identical gradient, so a repeated id resolves to the identical paint — and
   a *generated* id would differ between the server render and hydration,
   which is a real bug traded for a cosmetic one. */
const UID = "acl-mark";

export function LogoMark({ className }: { className?: string }) {
  const uid = UID;

  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden
      focusable="false"
      className={cn("size-7 shrink-0", className)}
    >
      <defs>
        <linearGradient id={`${uid}-face`} x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--iris-400)" />
          <stop offset="0.55" stopColor="var(--iris-600)" />
          <stop offset="1" stopColor="var(--indigo-600)" />
        </linearGradient>
        <linearGradient id={`${uid}-lit`} x1="10" y1="3" x2="20" y2="24" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--cyan-300)" stopOpacity="0.95" />
          <stop offset="1" stopColor="var(--iris-300)" stopOpacity="0.4" />
        </linearGradient>
      </defs>

      {/* the letterform: a triangle, split into facets that catch light
          differently — the same cut as the original chrome mark */}
      <path d="M16 2.6 30 29.4H2L16 2.6Z" fill={`url(#${uid}-face)`} />
      <path d="M16 2.6 16 29.4H2L16 2.6Z" fill="#000" fillOpacity="0.16" />
      <path d="M16 2.6l5.4 10.3-5.4 3.1-5.4-3.1L16 2.6Z" fill={`url(#${uid}-lit)`} />
      <path d="M10.6 12.9 16 16l-2.4 13.4H2l8.6-16.5Z" fill="#fff" fillOpacity="0.1" />

      {/* the aperture: six blades around an open center */}
      <g transform="translate(16 19.6)">
        <circle r="5.5" fill="var(--n-975)" fillOpacity="0.34" />
        {[0, 60, 120, 180, 240, 300].map((deg) => (
          <path
            key={deg}
            d="M0 -5.1 4.42 -2.55 0 0Z"
            fill="#fff"
            fillOpacity="0.9"
            transform={`rotate(${deg})`}
          />
        ))}
        <circle r="5.5" stroke="#fff" strokeOpacity="0.55" strokeWidth="1" />
      </g>
    </svg>
  );
}

/** Brand lockup: mark + wordmark.
 *
 * `tone` forces the wordmark color for surfaces that do not follow the theme
 * (an image overlay, a brand-filled banner). Left unset it inherits the
 * theme, which is what every in-app surface wants. */
export function Logo({
  tone,
  className,
  compact,
}: {
  tone?: "light" | "dark";
  className?: string;
  compact?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {!compact && (
        <span
          className={cn(
            "font-display text-[17px] leading-none font-extrabold tracking-tight",
            tone === "light"
              ? "text-white"
              : tone === "dark"
                ? "text-[#0b0b14]"
                : "text-strong"
          )}
        >
          AdCoherent{" "}
          <span
            className={cn(
              "font-semibold",
              tone === "light"
                ? "text-white/65"
                : tone === "dark"
                  ? "text-[#0b0b14]/60"
                  : "text-muted"
            )}
          >
            Labs
          </span>
        </span>
      )}
    </span>
  );
}
