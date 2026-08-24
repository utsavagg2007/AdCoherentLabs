import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit .next/standalone — a self-contained server plus only the traced
  // node_modules the app actually reaches. Required by frontend/Dockerfile and
  // by any deploy: without it the runtime image has to carry the full
  // node_modules tree (hundreds of MB) just to run `next start`.
  //
  // Caveat the tracer does not handle: `public/` and `.next/static` are NOT
  // copied into standalone (Next assumes a CDN fronts them). The Dockerfile
  // copies both by hand — drop those lines and the app boots but serves every
  // page unstyled and imageless.
  output: "standalone",
};

export default nextConfig;
