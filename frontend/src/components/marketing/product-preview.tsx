/** DOM-built product preview — a real recreation of the report experience,
 * clearly labeled illustrative. No generated screenshots, no customer data. */

import {
  BadgeCheck,
  FileCheck2,
  Fingerprint,
  Quote,
  Wrench,
} from "lucide-react";

export function ProductPreview() {
  return (
    <section id="preview" aria-label="Product preview" className="bg-cream/60">
      <div className="container-wide py-20 sm:py-28">
        <div className="mx-auto max-w-2xl text-center">
          <p className="eyebrow text-violet-600">The report</p>
          <h2 className="mt-3 text-4xl font-extrabold tracking-[-0.02em] text-ink-900 text-balance sm:text-5xl">
            Every finding arrives with its receipts.
          </h2>
          <p className="mt-4 text-[16px] leading-relaxed text-zinc-500 text-pretty">
            Quoted evidence, regulatory citations, concrete remediation, and a
            deterministic verification trail — organized for a compliance
            reviewer, not a data scientist.
          </p>
        </div>

        {/* browser frame */}
        <div className="relative mx-auto mt-14 max-w-5xl">
          <div
            aria-hidden
            className="absolute -inset-x-8 -bottom-10 top-24 rounded-[40px] bg-violet-200/30 blur-3xl"
          />
          <figure className="relative overflow-hidden rounded-2xl border border-line bg-white shadow-(--shadow-float)">
            <figcaption className="sr-only">
              Illustrative compliance report for a demo creative
            </figcaption>
            {/* chrome */}
            <div className="flex items-center gap-3 border-b border-line bg-cream/80 px-4 py-2.5">
              <div className="flex gap-1.5" aria-hidden>
                <span className="size-2.5 rounded-full bg-zinc-300" />
                <span className="size-2.5 rounded-full bg-zinc-300" />
                <span className="size-2.5 rounded-full bg-zinc-300" />
              </div>
              <div className="mx-auto flex h-7 w-full max-w-sm items-center justify-center gap-1.5 rounded-lg border border-line bg-white text-[11px] font-medium text-zinc-400">
                app.adcoherentlabs.com/runs/rep-demo
              </div>
              <span className="rounded-md border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-violet-700 uppercase">
                Illustrative
              </span>
            </div>

            <div className="grid md:grid-cols-[0.9fr_1.1fr]">
              {/* creative panel */}
              <div className="border-b border-line bg-cream/50 p-5 md:border-r md:border-b-0">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                    Creative
                  </p>
                  <span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] font-bold text-zinc-500">
                    Demo creative
                  </span>
                </div>
                {/* demo ad */}
                <div className="relative mt-3 overflow-hidden rounded-xl border border-line bg-white p-5 shadow-(--shadow-soft)">
                  <p className="text-[10px] font-bold tracking-widest text-violet-600 uppercase">
                    Apex Lending · Ad
                  </p>
                  {/* claim with bbox */}
                  <div className="relative mt-2 inline-block">
                    <p className="text-[21px] leading-tight font-extrabold text-ink-900">
                      Pay down debt <span className="text-violet-700">8× faster</span>*
                    </p>
                    <span
                      aria-hidden
                      className="pointer-events-none absolute -inset-1.5 rounded-md border-2 border-amber-400/80"
                    />
                    <span className="absolute -top-4 left-0 rounded-sm bg-amber-400 px-1 py-px text-[8.5px] font-bold text-amber-950">
                      claim clm_2
                    </span>
                  </div>
                  <p className="mt-3 text-[12.5px] leading-snug text-zinc-600">
                    Consolidate at a fixed rate with one monthly payment of
                    $1,068 over 60 months.
                  </p>
                  <div className="mt-3 inline-flex rounded-full bg-ink-900 px-3.5 py-1.5 text-[11px] font-bold text-white">
                    Check your rate
                  </div>
                  {/* disclosure with bbox */}
                  <div className="relative mt-4">
                    <p className="rounded-md bg-cream px-2 py-1.5 text-[9.5px] leading-relaxed text-zinc-500">
                      *Example based on a $40,000 loan, 20.39% APR, 60-month
                      term. Your rate, payment, and total interest may vary
                      based on credit history, loan amount, and term.
                    </p>
                    <span
                      aria-hidden
                      className="pointer-events-none absolute -inset-1 rounded-md border-2 border-violet-500/70"
                    />
                    <span className="absolute -top-2 right-0 rounded-sm bg-violet-600 px-1 py-px text-[8.5px] font-bold text-white">
                      disclosure seg_7
                    </span>
                  </div>
                </div>
                <p className="mt-3 text-[11px] leading-relaxed text-zinc-400">
                  Bounding boxes locate each claim and disclosure in the
                  creative when coordinates are available.
                </p>
              </div>

              {/* report panel */}
              <div className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                    Review findings
                  </p>
                  <div className="flex items-center gap-1.5 text-[11px] font-bold">
                    <span className="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-red-700">
                      1 High
                    </span>
                    <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-amber-800">
                      1 Medium
                    </span>
                    <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-emerald-700">
                      2 Low
                    </span>
                  </div>
                </div>

                {/* finding card */}
                <article className="mt-3 rounded-xl border border-line bg-white p-4 shadow-(--shadow-soft)">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[10.5px] font-bold text-red-700">
                      High
                    </span>
                    <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[10.5px] font-bold text-zinc-600">
                      Potential violation
                    </span>
                    <span className="ml-auto rounded-md border border-violet-200 bg-violet-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-violet-800">
                      12 CFR §1026.24(d)
                    </span>
                  </div>
                  <h3 className="mt-2.5 text-[13.5px] leading-snug font-bold text-ink-900">
                    Triggering terms require a clear-and-conspicuous APR
                    disclosure
                  </h3>
                  <blockquote className="mt-2.5 flex gap-2 rounded-lg border-l-2 border-violet-400 bg-violet-50/60 p-2.5">
                    <Quote className="size-3 shrink-0 text-violet-400" aria-hidden />
                    <p className="text-[12px] leading-relaxed text-ink-700 italic">
                      “…one monthly payment of $1,068 over 60 months.”
                    </p>
                  </blockquote>
                  <div className="mt-2.5 flex items-start gap-2 rounded-lg bg-cream p-2.5">
                    <Wrench className="mt-0.5 size-3 shrink-0 text-zinc-400" aria-hidden />
                    <p className="text-[12px] leading-relaxed text-zinc-600">
                      Move the APR into the same visual field as the payment
                      claim, at comparable prominence to the triggering terms.
                    </p>
                  </div>
                </article>

                {/* verification & provenance */}
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <div className="rounded-xl border border-line bg-white p-3.5">
                    <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                      <BadgeCheck className="size-3.5 text-emerald-600" aria-hidden />
                      Verification
                    </p>
                    <ul className="mt-2 space-y-1 text-[11.5px] text-zinc-600">
                      <li className="flex justify-between">
                        <span>Deterministic checks</span>
                        <span className="font-bold text-ink-800">52 run</span>
                      </li>
                      <li className="flex justify-between">
                        <span>Review soundness</span>
                        <span className="font-bold text-emerald-700">Passed</span>
                      </li>
                      <li className="flex justify-between">
                        <span>Audit rounds</span>
                        <span className="font-bold text-ink-800">2</span>
                      </li>
                    </ul>
                  </div>
                  <div className="rounded-xl border border-line bg-white p-3.5">
                    <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                      <Fingerprint className="size-3.5 text-violet-600" aria-hidden />
                      Provenance
                    </p>
                    <ul className="mt-2 space-y-1 font-mono text-[10.5px] text-zinc-500">
                      <li className="truncate">prompt v1.3 · ruleset v2.1</li>
                      <li className="truncate">corpus 9c41d2ab77e01f45</li>
                      <li className="truncate">reviewed 09:30:14 UTC</li>
                    </ul>
                  </div>
                </div>

                <p className="mt-3 flex items-center gap-1.5 text-[11px] text-zinc-400 italic">
                  <FileCheck2 className="size-3.5" aria-hidden />
                  Decision support, not legal advice.
                </p>
              </div>
            </div>
          </figure>
        </div>
      </div>
    </section>
  );
}
