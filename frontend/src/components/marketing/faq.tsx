"use client";

import { Accordion, AccordionItem } from "@/components/ui/accordion";

const FAQS = [
  {
    q: "What kinds of ads can I review?",
    a: "v1 analyzes pasted text, pasted HTML, and uploaded PNG, JPEG, WebP, GIF, TXT, and HTML files — plus image carousels of up to 10 cards reviewed as a single submission. PDF and video uploads are accepted for storage but are not analyzable in v1.",
  },
  {
    q: "Does AdCoherent Labs replace legal counsel?",
    a: "No. Reports are decision support for your compliance process — structured evidence, citations, and deterministic checks that make your team's review faster and more consistent. They are not legal advice, and nothing in the product grants or implies legal approval of an ad.",
  },
  {
    q: "How are findings supported?",
    a: "Every finding quotes the exact creative copy it concerns, cites the regulatory excerpts it relied on (for example, 12 CFR §1026.24(d)), explains its reasoning, and proposes a concrete remediation. A deterministic rule engine then audits the AI review itself — findings ship with the verification outcome and full provenance: model, prompt version, ruleset version, and corpus fingerprint.",
  },
  {
    q: "What happens when a review needs human input?",
    a: "If the automated loop can't converge — for example, the deterministic checks keep failing the AI's review — the run pauses in a human-review state with specific instructions about what remained unresolved. A reviewer adds guidance and resumes the run. The resumed run is linked to the original and costs zero additional credits.",
  },
  {
    q: "How are creatives handled?",
    a: "Uploads pass a security pipeline before anything else happens: MIME sniffing against an allowlist, per-plan size caps, malware scanning, and re-encoding of raster images to strip metadata and embedded payloads. Files that fail any step are rejected and never charged. Stored creatives live in your organization's private storage, accessible to members through short-lived signed URLs.",
  },
  {
    q: "Can I review a carousel?",
    a: "Yes — upload up to 10 image cards as one submission. The review walks every card and the report attributes evidence per card. Pricing is the image cost for the first card plus a smaller per-card cost for each additional card, shown before you submit.",
  },
];

export function Faq() {
  return (
    <section id="faq" aria-label="Frequently asked questions" className="bg-cream/60">
      <div className="container-page py-20 sm:py-28">
        <div className="mx-auto max-w-3xl">
          <p className="eyebrow text-violet-600">FAQ</p>
          <h2 className="mt-3 text-4xl font-extrabold tracking-[-0.02em] text-ink-900 text-balance">
            Precise answers to fair questions.
          </h2>
          <Accordion type="single" collapsible className="mt-10">
            {FAQS.map((f, i) => (
              <AccordionItem key={i} value={`faq-${i}`} question={f.q}>
                {f.a}
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </div>
    </section>
  );
}
