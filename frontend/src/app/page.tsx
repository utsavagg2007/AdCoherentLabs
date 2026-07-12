import Link from "next/link";
import {
  ArrowRight,
  Check,
  FileSearch,
  Fingerprint,
  Gauge,
  Landmark,
  Lock,
  Radar,
  Scale,
  ScanEye,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { Logo } from "@/components/logo";
import { buttonClasses } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { TIER_DISPLAY, TIERS } from "@/lib/entitlements";
import { isDemoMode } from "@/lib/env";
import { cn } from "@/lib/utils";

const LAYERS = [
  {
    tag: "L1",
    name: "Computer Vision",
    icon: ScanEye,
    text: "OCR, layout and region detection turn banners, PDFs, video frames and rendered landing pages into positioned text — plus visual findings like 6px fine print, low contrast, or a disclosure below the fold.",
  },
  {
    tag: "L2",
    name: "NLP & Framework Routing",
    icon: Workflow,
    text: "Deterministic segmentation, claim extraction and disclosure detection. Every asset is classified and routed to the right regulatory frameworks — FTC, SEC, SEBI, RBI, GDPR — before a single LLM token is spent.",
  },
  {
    tag: "L3",
    name: "LLM Reasoning",
    icon: Radar,
    text: "Retrieval-grounded reasoning over an 11k-chunk regulation corpus. Structured findings with severity, rule citation, confidence and suggested remediation — the model must cite, never invent.",
  },
  {
    tag: "L4",
    name: "Deterministic Rule Engine",
    icon: Scale,
    text: "Versioned jurisdiction rule packs confirm, override or escalate every LLM finding — cutting false positives and false negatives, and turning a probabilistic judgement into a defensible verdict.",
  },
];

const FEATURES = [
  {
    icon: Gauge,
    title: "Realtime analysis viewer",
    text: "Watch a run move through all four layers live, then read findings overlaid on the exact region of the creative that triggered them.",
  },
  {
    icon: Landmark,
    title: "Five regulatory frameworks",
    text: "FTC, SEC, SEBI, RBI and GDPR rule packs, versioned and recorded on every run so verdicts stay reproducible as regulation drifts.",
  },
  {
    icon: Lock,
    title: "Tenant isolation by design",
    text: "Row-Level Security on every table, org-scoped storage, and a cross-tenant access test that gates every release.",
  },
  {
    icon: Fingerprint,
    title: "Tamper-evident audit trail",
    text: "Every security- and compliance-relevant action lands in a hash-chained audit log. Any retroactive edit breaks the chain.",
  },
  {
    icon: FileSearch,
    title: "Auditable, exportable reports",
    text: "Model ID, prompt version, rule-pack version, tokens and cost recorded per run. Export findings as JSON or CSV for your compliance file.",
  },
  {
    icon: ShieldCheck,
    title: "Hostile-input hardened",
    text: "Malware scanning, MIME sniffing, SSRF-guarded URL fetching and prompt-injection defence — ad creatives are treated as adversarial input.",
  },
];

export default function LandingPage() {
  const appHref = isDemoMode ? "/dashboard" : "/signup";
  return (
    <div className="min-h-screen">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-line/70 bg-canvas/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <Link href="/" aria-label="AdCoherent Labs home">
            <Logo />
          </Link>
          <nav className="hidden items-center gap-7 text-sm text-ink-dim md:flex">
            <a href="#engine" className="hover:text-ink">The engine</a>
            <a href="#features" className="hover:text-ink">Platform</a>
            <a href="#pricing" className="hover:text-ink">Pricing</a>
          </nav>
          <div className="flex items-center gap-3">
            <Link href="/login" className={buttonClasses("ghost", "sm")}>
              Sign in
            </Link>
            <Link href={appHref} className={buttonClasses("primary", "sm")}>
              {isDemoMode ? "Open demo" : "Get started"}
              <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="bg-grid absolute inset-0 [mask-image:radial-gradient(60%_60%_at_50%_35%,black,transparent)]" />
        <div
          aria-hidden
          className="absolute left-1/2 top-[-180px] h-[420px] w-[720px] -translate-x-1/2 rounded-full bg-brand/10 blur-3xl"
        />
        <div className="relative mx-auto max-w-6xl px-5 pb-20 pt-20 text-center sm:pt-28">
          <Badge className="mx-auto mb-6 border-brand/30 bg-brand/10 text-brand">
            <span className="size-1.5 rounded-full bg-brand" />
            Four-layer AI compliance engine · v1.0
          </Badge>
          <h1 className="mx-auto max-w-3xl text-balance text-4xl font-semibold tracking-tight sm:text-6xl">
            Ship regulated fintech marketing{" "}
            <span className="bg-gradient-to-r from-brand-bright to-emerald-500 bg-clip-text text-transparent">
              without the compliance bottleneck
            </span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-pretty text-base leading-relaxed text-ink-dim sm:text-lg">
            Upload an ad. AdCoherent extracts every claim and disclosure, reasons
            over FTC, SEC, SEBI, RBI and GDPR with a retrieval-grounded LLM, then
            reconciles the judgement against deterministic rule packs. You get an
            auditable verdict in minutes — not a legal opinion, a head start.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-4">
            <Link href={appHref} className={buttonClasses("primary", "lg")}>
              {isDemoMode ? "Explore the live demo" : "Start free — 20 scans/mo"}
              <ArrowRight size={16} />
            </Link>
            <a href="#engine" className={buttonClasses("secondary", "lg")}>
              How the engine works
            </a>
          </div>
          <p className="mt-5 text-xs text-ink-faint">
            Decision support for compliance teams — not legal advice. Humans keep
            final approval.
          </p>
        </div>
      </section>

      {/* Trust strip */}
      <section className="border-y border-line bg-surface/60">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-5 py-8 text-center sm:grid-cols-4">
          {[
            ["5", "regulatory frameworks"],
            ["4", "analysis layers per scan"],
            ["11k+", "regulation chunks in corpus"],
            ["100%", "runs with full provenance"],
          ].map(([n, label]) => (
            <div key={label}>
              <p className="font-mono text-2xl font-semibold text-brand">{n}</p>
              <p className="mt-1 text-xs text-ink-dim">{label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Engine */}
      <section id="engine" className="mx-auto max-w-6xl scroll-mt-24 px-5 py-24">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            The engine is the product
          </h2>
          <p className="mt-4 text-ink-dim">
            One scan walks four layers in order. Every layer&apos;s output is
            persisted, versioned and reproducible — a compliance verdict you can
            explain to an auditor, not a black box.
          </p>
        </div>
        <div className="mt-14 grid gap-4 lg:grid-cols-2">
          {LAYERS.map((layer, i) => (
            <div
              key={layer.tag}
              className="group relative rounded-2xl border border-line bg-surface p-6 transition-colors hover:border-brand/30"
            >
              <div className="flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-xl bg-brand/10 text-brand">
                  <layer.icon size={19} />
                </span>
                <div>
                  <p className="font-mono text-[11px] text-ink-faint">
                    LAYER {i + 1}
                  </p>
                  <h3 className="text-base font-semibold">{layer.name}</h3>
                </div>
              </div>
              <p className="mt-4 text-sm leading-relaxed text-ink-dim">
                {layer.text}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section id="features" className="border-t border-line bg-surface/40">
        <div className="mx-auto max-w-6xl scroll-mt-24 px-5 py-24">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              Built like the compliance product it audits
            </h2>
            <p className="mt-4 text-ink-dim">
              Multi-tenant isolation, hostile-input handling and audit integrity
              are architecture, not afterthoughts.
            </p>
          </div>
          <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="rounded-2xl border border-line bg-surface p-6"
              >
                <span className="grid size-9 place-items-center rounded-lg bg-raised text-brand">
                  <f.icon size={17} />
                </span>
                <h3 className="mt-4 text-sm font-semibold">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-dim">
                  {f.text}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="mx-auto max-w-6xl scroll-mt-24 px-5 py-24">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            A tier for every review load
          </h2>
          <p className="mt-4 text-ink-dim">
            The engine is identical on every plan — only the reasoning model,
            quotas and governance change. Cancel anytime.
          </p>
        </div>
        <div className="mt-14 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          {TIERS.map((tier) => {
            const d = TIER_DISPLAY[tier];
            return (
              <div
                key={tier}
                className={cn(
                  "flex flex-col rounded-2xl border p-6",
                  d.highlight
                    ? "border-brand/40 bg-brand/5 shadow-[0_0_40px_-16px] shadow-brand/40"
                    : "border-line bg-surface",
                )}
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{d.name}</h3>
                  {d.highlight && (
                    <Badge className="border-brand/30 bg-brand/10 text-brand">
                      Popular
                    </Badge>
                  )}
                </div>
                <p className="mt-3">
                  {d.priceMonthly == null ? (
                    <span className="text-2xl font-semibold">Custom</span>
                  ) : (
                    <>
                      <span className="text-3xl font-semibold">
                        ${d.priceMonthly}
                      </span>
                      <span className="text-xs text-ink-faint"> /mo</span>
                    </>
                  )}
                </p>
                <p className="mt-2 text-xs leading-relaxed text-ink-dim">
                  {d.blurb}
                </p>
                <ul className="mt-5 flex-1 space-y-2.5">
                  {d.features.map((f) => (
                    <li key={f} className="flex gap-2 text-xs text-ink-dim">
                      <Check size={13} className="mt-0.5 shrink-0 text-brand" />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href={appHref}
                  className={cn(
                    "mt-6",
                    buttonClasses(d.highlight ? "primary" : "secondary", "sm"),
                    "w-full",
                  )}
                >
                  {tier === "enterprise" ? "Talk to us" : "Get started"}
                </Link>
              </div>
            );
          })}
        </div>
        <p className="mt-6 text-center text-xs text-ink-faint">
          Prices are launch placeholders — quotas map to the entitlements table
          in the data plane.
        </p>
      </section>

      {/* Footer */}
      <footer className="border-t border-line">
        <div className="mx-auto max-w-6xl px-5 py-10">
          <div className="flex flex-col items-start justify-between gap-6 sm:flex-row sm:items-center">
            <Logo />
            <nav className="flex gap-6 text-xs text-ink-dim">
              <a href="#engine" className="hover:text-ink">Engine</a>
              <a href="#pricing" className="hover:text-ink">Pricing</a>
              <Link href="/login" className="hover:text-ink">Sign in</Link>
            </nav>
          </div>
          <p className="mt-8 max-w-3xl text-[11px] leading-relaxed text-ink-faint">
            AdCoherent assists marketing-compliance review; it does not replace a
            compliance officer and its output does not constitute legal advice.
            Findings are decision support with confidence scores — final approval
            stays with an accountable human. © 2026 AdCoherent Labs.
          </p>
        </div>
      </footer>
    </div>
  );
}
