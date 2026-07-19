# AdCoherent Labs — Frontend

Production frontend for the AdCoherent Labs compliance-review platform:
a cinematic marketing site plus the authenticated review application.

- **Stack**: Next.js 16 (App Router, Turbopack), TypeScript, Tailwind CSS v4,
  Radix primitives, Lucide icons. Font: Manrope.
- **Data plane**: Supabase is used **only** for authentication/session,
  RLS-safe organization discovery, realtime assist, and short-lived storage
  signed URLs. Every business read/write goes through the FastAPI backend via
  one typed client ([src/lib/api.ts](src/lib/api.ts)).

## Quick start

```bash
npm install
cp .env.example .env.local   # fill in values (see below)
npm run dev                  # http://localhost:3000
```

| Variable | Meaning |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | Kong URL of the Supabase stack (dev: `http://localhost:8000`) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | The stack's public anon key |
| `NEXT_PUBLIC_API_URL` | FastAPI base URL (dev: `http://localhost:8080`) |

Never put service-role keys, database URLs, Stripe secrets, or JWT signing
secrets anywhere in this app.

```bash
npm run lint   # eslint (zero warnings enforced in CI-style runs)
npm run build  # production build
```

## Layout

```
src/
  app/
    page.tsx              marketing landing page
    (auth)/               login · signup · forgot/reset password
    onboarding/           first-organization flow
    (app)/                authenticated shell (sidebar, org switcher)
      dashboard/          composed from /v1/orgs/me, /v1/credits, /v1/runs…
      submissions/        history · detail · new (the compliance workbench)
      runs/[id]/          run tracking + the full report experience
      reports/            run history + findings review queue
      billing/            balance, ledger, price list, Stripe redirects
      settings/           workspace + team; settings/api-keys
  components/             providers, ui kit, marketing, app, report renderers
  lib/                    typed API client, types, supabase, hooks, labels
scripts/render-clips.js   deterministic generator for the three hero clips
public/videos/            hero-assembly · signal-evidence · calm-review (+ posters)
```

## API client contract

[src/lib/api.ts](src/lib/api.ts) sends `Authorization: Bearer <supabase JWT>`
plus `X-Org-Id` on every request once an organization is selected, supports
`X-API-Key` mode, and normalizes the backend error envelope
(`{error:{code,message,request_id,details}}`) including 402 credits, 409
not-ready, 413/415 upload rejections, 422 scanner issues, 429 with
Retry-After, and 503 outages. Submissions carry an `Idempotency-Key` that is
**never rotated silently** — an identical retry replays the identical key.

## The three cinematic clips

The marketing page uses three ~8 s 1080p clips in `public/videos/`:

1. `hero-assembly.mp4` — scroll-scrubbed hero (chaos → assembled dashboard)
2. `signal-evidence.mp4` — pinned Extract/Ground/Defend backdrop
3. `calm-review.mp4` — final CTA backdrop

They are generated **deterministically** by `scripts/render-clips.js`
(node-canvas → ffmpeg, dense keyframes for smooth `currentTime` scrubbing):

```bash
npm i -D @napi-rs/canvas ffmpeg-static     # generator-only deps
node scripts/render-clips.js all public/videos
```

They were art-directed as stand-ins for the intended Higgsfield/Seedance 2.0
renders (generation was blocked: the connected Higgsfield account is on the
free plan — Seedance requires Pro/Ultimate). To swap in Seedance clips later,
render with the prompts in the project brief and overwrite the three `.mp4`
files (16:9, ~8 s, silent; keep filenames) plus the `*-poster.jpg` /
`*-still.jpg` frames. No code changes needed — all UI text is DOM overlay by
design.

## Motion & accessibility

- The hero implements true scroll-to-video-time scrubbing
  (`requestAnimationFrame` + passive scroll listener, metadata guards, eased
  seeking). Scrolling is never trapped.
- Every cinematic sequence has a `prefers-reduced-motion` fallback (static
  stills, no counters, no scrub track) — the fallback is also the SSR state.
- Radix dialogs/accordions/tabs/dropdowns, labeled controls, focus-visible
  styles, semantic headings, keyboard-reachable everything.

## Product-truth guardrails

No invented dollar prices (Stripe checkout owns pricing), no annual billing
toggle (backend doesn't implement annual pricing), no fake logos/testimonials/
accuracy stats, and the "decision support, not legal advice" disclaimer rides
on every report surface.
