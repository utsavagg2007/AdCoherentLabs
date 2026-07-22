"use client";

import { Accordion, AccordionItem } from "@/components/ui/accordion";

const FAQS = [
  {
    q: "What kinds of ads can I review?",
    a: "Pasted text or HTML, uploaded images (PNG, JPEG, WebP, GIF — including carousels of up to 10 cards), PDFs, Word documents, and video (MP4, MOV, WebM). Which formats your workspace can submit depends on plan: Free covers text, images, PDFs and documents; Hobby adds video up to one minute; Pro and above run full-length video. Video is analysed frame-by-frame through the same vision pipeline.",
  },
  {
    q: "Does AdCoherent Labs replace legal counsel?",
    a: "No. Reports are decision support for your compliance process — structured evidence, citations, and deterministic checks that make your team's review faster and more consistent. They are not legal advice, and nothing in the product grants or implies legal approval of an ad.",
  },
  {
    q: "What do I see while a review runs?",
    a: "A live activity feed narrates every stage the moment it happens: what was extracted, how many claims were found, which frameworks were routed, how each review round went, and what verification concluded. The feed carries stage names and aggregate counts only — your creative's content, retrieved regulation text, and the model's reasoning never appear in it.",
  },
  {
    q: "How are findings supported?",
    a: "Every finding quotes the exact creative copy it concerns, cites the regulatory excerpts it relied on (for example, 12 CFR §1026.24(d)), explains its reasoning, and proposes concrete remediation steps — as suggestions for your compliance team, never as legal clearance. A deterministic rule engine then audits the AI review itself, and findings ship with the verification outcome and full provenance.",
  },
  {
    q: "How does credit pricing work?",
    a: "A run charges its published base price up front — it covers extraction, retrieval and verification. When the run finishes, its actual model usage is settled from the tokens consumed, at per-tier rates published on the pricing endpoint. Both components appear on the report and in your ledger, line by line.",
  },
  {
    q: "What happens when a review needs human input?",
    a: "If the automated loop can't converge — for example, the deterministic checks keep failing the AI's review — the run pauses in a human-review state with specific instructions about what remained unresolved. A reviewer adds guidance and resumes the run. The resumed run is linked to the original and costs zero additional credits.",
  },
  {
    q: "How are creatives handled?",
    a: "Uploads pass a security pipeline before anything else happens: MIME sniffing against an allowlist, per-plan size and length caps, malware scanning, and re-encoding of raster images to strip metadata and embedded payloads. Files that fail any step are rejected and never charged. Stored creatives live in your organization's private storage, accessible to members through short-lived signed URLs.",
  },
];

export function Faq() {
  return (
    <section id="faq" aria-label="Frequently asked questions" className="bg-coal-900">
      <div className="container-page py-20 sm:py-28">
        <div className="mx-auto max-w-3xl">
          <p className="eyebrow">FAQ</p>
          <h2 className="text-chrome mt-3 font-display text-4xl font-bold tracking-[-0.02em] text-balance">
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
