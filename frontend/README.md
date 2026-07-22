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
python ../scripts/sync_env.py --only frontend   # generates .env.local from the stack env
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

## Brand media

`public/media/` holds the generated brand assets (2026-07-22, chrome
monolith theme matched to `public/brand/` logos):

1. `hero-still.jpg` (+ `hero-blur.jpg` placeholder) — Runway nano-banana-pro
   still; the SSR/reduced-motion hero state and the final-CTA backdrop
2. `hero-loop.mp4` — a single ~5 s gen-4-turbo ambient loop animated from
   that still; plain `autoplay muted loop playsInline`

There is **no scroll-scrubbing anywhere** — the old scroll-to-video-time
hero was removed deliberately (it read as lag). Scrolling never drives
media; section reveals use one IntersectionObserver (`marketing/reveal.tsx`)
and CSS transitions only.

## Motion & accessibility

- Motion budget: the hero loop + IO reveals + a CSS marquee (pauses on
  hover). Every one respects `prefers-reduced-motion` (the still/final
  states are also the SSR states).
- Radix dialogs/accordions/tabs/dropdowns, labeled controls, focus-visible
  styles, semantic headings, keyboard-reachable everything.

## Product-truth guardrails

No invented dollar prices (Stripe checkout owns pricing), no annual billing
toggle (backend doesn't implement annual pricing), no fake logos/testimonials/
accuracy stats, and the "decision support, not legal advice" disclaimer rides
on every report surface.
