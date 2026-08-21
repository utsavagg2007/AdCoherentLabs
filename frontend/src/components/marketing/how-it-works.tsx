import {
  ScanSearch,
  MessageSquareText,
  BookOpenCheck,
  ShieldCheck,
} from "lucide-react";
import { Reveal } from "./reveal";

/** The four-layer pipeline, told as a vertical walkthrough. Replaces the
 * old pinned scroll-scrub section: every element is static content that
 * reveals once — scrolling never drives media. */

const LAYERS = [
  {
    icon: ScanSearch,
    layer: "Layer 1",
    name: "Computer vision",
    copy: "OCR reads every word off images, video keyframes, and rendered PDF pages — then measures what a regulator would: text size, contrast, and how far each disclosure sits from the claim it qualifies.",
    facts: ["OCR + layout geometry", "Video keyframes & PDF pages", "Disclosure proximity"],
  },
  {
    icon: MessageSquareText,
    layer: "Layer 2",
    name: "Language analysis",
    copy: "Deterministic NLP segments the creative, extracts rates, fees, and entities, flags claim candidates, and routes the ad to the regulatory frameworks it actually implicates.",
    facts: ["Claim detection", "Entity & rate extraction", "Framework routing"],
  },
  {
    icon: BookOpenCheck,
    layer: "Layer 3",
    name: "Grounded AI review",
    copy: "Your tier's model reviews every claim against retrieved regulation text — the actual CFR excerpts, not a summary — and must cite what it relied on for every finding.",
    facts: ["Regulation retrieval", "Citation-backed findings", "Tier-routed models"],
  },
  {
    icon: ShieldCheck,
    layer: "Layer 4",
    name: "Deterministic verification",
    copy: "A rule engine audits the AI's review itself — 50+ checks for soundness and coverage. If the review fails, the engine sends fix instructions back to the model; if it can't converge, a human reviewer takes over.",
    facts: ["50+ deterministic checks", "Automatic model callbacks", "Human-review escalation"],
  },
];

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      aria-label="How the four-layer review works"
      className="relative bg-canvas"
    >
      <div className="container-page py-20 sm:py-28">
        <Reveal className="max-w-2xl">
          <p className="eyebrow">How it works</p>
          <h2 className="text-gradient mt-3 font-display text-4xl font-bold tracking-[-0.02em] text-balance sm:text-5xl">
            Four layers. One verified answer.
          </h2>
          <p className="mt-4 max-w-xl text-[15.5px] leading-relaxed text-muted text-pretty">
            Each layer hands structured evidence to the next. Nothing reaches
            your report without passing deterministic verification.
          </p>
        </Reveal>

        <ol className="relative mt-14 space-y-5 sm:mt-16">
          {/* connective spine */}
          <div
            aria-hidden
            className="absolute top-4 bottom-4 left-[27px] hidden w-px bg-gradient-to-b from-white/20 via-white/10 to-transparent sm:block"
          />
          {LAYERS.map((l, i) => (
            <Reveal as="li" key={l.name} delay={i * 70} className="relative">
              <div className="card flex flex-col gap-5 p-6 sm:flex-row sm:gap-7 sm:p-7">
                <div className="relative flex size-14 shrink-0 items-center justify-center rounded-2xl border border-line bg-hover shadow-(--shadow-soft)">
                  <l.icon className="size-6 text-body" aria-hidden />
                </div>
                <div className="min-w-0">
                  <p className="font-mono text-[11px] font-bold tracking-[0.2em] text-subtle uppercase">
                    {l.layer}
                  </p>
                  <h3 className="mt-1 font-display text-xl font-bold text-strong">
                    {l.name}
                  </h3>
                  <p className="mt-2 max-w-2xl text-[14.5px] leading-relaxed text-muted">
                    {l.copy}
                  </p>
                  <ul className="mt-4 flex flex-wrap gap-2">
                    {l.facts.map((f) => (
                      <li key={f} className="badge-neutral">
                        {f}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}
