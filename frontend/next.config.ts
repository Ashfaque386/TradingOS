import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Phase 2 verification pass: Turbopack's own workspace-root auto-inference started
  // misidentifying `src/app` itself as the project root ("couldn't find next/package.json from
  // the project directory: /app/src/app"), reproducible across repeated `next build` runs with
  // node_modules/next verifiably present and valid at the real root. Explicitly pinning the root
  // (Next.js's own documented fix for this exact error) removes the ambiguity outright rather
  // than relying on inference in a Docker bind-mount setup with no sibling lockfiles to confuse it.
  turbopack: {
    root: __dirname,
  },
  // REL-009 E9.6: real root cause of every Cypress login-form failure this session, confirmed
  // via the dev server's own log -- "Blocked cross-origin request to Next.js dev resource
  // /_next/webpack-hmr from 'frontend'". Cypress must visit via the docker-network hostname
  // (http://frontend:3000, not localhost) so its own network calls to http://app:8000 work, but
  // Next.js 16's dev server blocks the webpack-hmr WebSocket for any origin other than
  // localhost by default -- with that connection rejected, the client-side dev runtime never
  // finishes bootstrapping, leaving the page's SSR'd HTML unhydrated (no React event delegation
  // attached), so every form submission silently fell through to the browser's native HTML
  // submit instead of React's onSubmit handler. Confirmed as the actual cause, not a guess: the
  // identical interaction via `http://localhost:3000` (a real browser, not blocked) always
  // worked correctly.
  allowedDevOrigins: ["frontend", "app", "localhost"],
};

export default nextConfig;
