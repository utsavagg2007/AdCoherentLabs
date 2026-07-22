/** Framework/context rail — a slow chrome marquee on brushed metal.
 * Deliberately not a social-proof strip: these are the frameworks the
 * engine grounds against, duplicated once for a seamless CSS loop
 * (pauses on hover; static wrap under reduced motion). */

const FRAMEWORKS = [
  "FTC",
  "TILA / Regulation Z",
  "Regulation DD",
  "CFPB / UDAAP",
  "State UDAP",
  "FDIC advertising",
  "SEC marketing",
  "FINRA 2210",
];

function Chip({ label }: { label: string }) {
  return (
    <li className="shrink-0 rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 font-mono text-[13px] font-semibold tracking-tight whitespace-nowrap text-ink-700">
      {label}
    </li>
  );
}

export function FrameworkRail() {
  return (
    <section
      aria-label="Regulatory frameworks in scope"
      className="relative overflow-hidden border-b border-line bg-brushed"
    >
      <div className="py-12 sm:py-14">
        <p className="eyebrow text-center">
          Reviews grounded in the frameworks fintech ads answer to
        </p>
        <div
          className="relative mt-7 overflow-hidden"
          style={{
            maskImage:
              "linear-gradient(90deg, transparent, black 12%, black 88%, transparent)",
            WebkitMaskImage:
              "linear-gradient(90deg, transparent, black 12%, black 88%, transparent)",
          }}
        >
          <ul
            className="animate-marquee flex w-max items-center gap-3 motion-reduce:w-full motion-reduce:flex-wrap motion-reduce:justify-center"
            style={{ "--marquee-duration": "36s" } as React.CSSProperties}
          >
            {FRAMEWORKS.map((f) => (
              <Chip key={f} label={f} />
            ))}
            {FRAMEWORKS.map((f) => (
              <Chip key={`${f}-dup`} label={f} />
            ))}
          </ul>
        </div>
        <p className="mx-auto mt-7 max-w-xl px-5 text-center text-[13px] leading-relaxed text-ink-500">
          Applicable coverage for any given review is determined by the
          creative, detected product signals, target jurisdictions, and your
          plan&apos;s framework scope.
        </p>
      </div>
    </section>
  );
}
