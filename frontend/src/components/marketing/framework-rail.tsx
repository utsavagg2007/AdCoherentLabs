/** Framework/context rail — deliberately not a social-proof strip. */

const FRAMEWORKS = [
  "FTC",
  "TILA / Regulation Z",
  "Regulation DD",
  "CFPB / UDAAP",
  "State UDAP",
  "FDIC advertising",
];

export function FrameworkRail() {
  return (
    <section
      aria-label="Regulatory frameworks in scope"
      className="border-b border-line bg-paper"
    >
      <div className="container-page py-12 sm:py-14">
        <p className="eyebrow text-center text-zinc-400">
          Reviews grounded in the frameworks fintech ads answer to
        </p>
        <ul className="mt-6 flex flex-wrap items-center justify-center gap-x-3 gap-y-3">
          {FRAMEWORKS.map((f) => (
            <li
              key={f}
              className="rounded-full border border-line bg-white px-4 py-2 font-mono text-[13px] font-semibold tracking-tight text-ink-700 shadow-(--shadow-soft)"
            >
              {f}
            </li>
          ))}
        </ul>
        <p className="mx-auto mt-6 max-w-xl text-center text-[13px] leading-relaxed text-zinc-400">
          Applicable coverage for any given review is determined by the
          creative, detected product signals, target jurisdictions, and your
          plan&apos;s framework scope.
        </p>
      </div>
    </section>
  );
}
