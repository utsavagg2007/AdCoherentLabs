# AdCoherent frontend — Next.js 16, standalone output.
#
#   docker compose build frontend          # from the repo root
#   docker build -t adcoherent-frontend:prod \
#     --build-arg NEXT_PUBLIC_API_URL=https://api.example.com frontend/
#
# THE THING THAT CATCHES PEOPLE OUT: every NEXT_PUBLIC_* value is inlined into
# the client JavaScript by `next build`. They are BUILD-time inputs, not
# run-time ones. Passing them with `docker run -e` or a Cloud Run env var does
# nothing — the strings are already baked into the bundle. That is why they are
# ARGs here, and why changing the API URL means a rebuild, not a restart.
#
# Corollary: only ever pass PUBLIC values as build args. They end up readable by
# every visitor AND recorded in the image's layer history. The anon key is
# designed for that (row-level security constrains it); the service_role key
# would be a full database compromise.

# =============================================================================
# deps — install from the lockfile only, so this layer caches until deps change
# =============================================================================
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# `npm ci` (not `npm install`): reproducible, and it fails loudly when
# package.json and the lockfile have drifted apart.
RUN npm ci

# =============================================================================
# builder — compile the app
# =============================================================================
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# =============================================================================
# runner — minimal image: the standalone server, nothing else
# =============================================================================
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Unprivileged user. Safe here (unlike the backend image) because the Next
# server writes nothing outside its own cache dir.
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# The standalone bundle carries its own minimal server.js and the traced subset
# of node_modules.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
# ...but NOT these two. `output: "standalone"` deliberately omits public/ and
# .next/static because Vercel serves them from a CDN. Self-hosted, they must be
# copied in or the site renders with no CSS, no JS chunks and no images —
# which looks like an app bug, not a packaging one.
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

# server.js honours PORT and HOSTNAME. HOSTNAME=0.0.0.0 is required: the
# default binds localhost inside the container's own namespace, so Docker port
# publishing and Cloud Run health checks both see a dead port.
ENV PORT=3000 \
    HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
