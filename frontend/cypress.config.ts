import { defineConfig } from "cypress";

// REL-009 E9.6: real E2E specs against the real running stack (frontend + app + postgres) --
// no mocked network layer. `baseUrl`/`apiUrl` default to the same values the dev-mode compose
// stack already uses (frontend:3000, app:8001) so `npx cypress run` from inside `frontend/`
// works unchanged whether run on a dev machine or inside `ci.yml`'s job.
//
// Found 2026-09-05: this config's own apiUrl only controls what THIS test file's own
// `cy.request()` calls hit -- it does NOT control what the app's own browser-side fetch() calls
// hit, which is baked in at frontend-container-start time via NEXT_PUBLIC_API_BASE_URL
// (docker-compose.yml). That var's real default is `https://localhost:8443` (GLH-02, self-signed
// TLS) -- fine for a human who's already clicked through the cert warning once, but a real,
// confirmed, repeatable source of login-timeout flakes for `npx cypress run` from a host outside
// the docker network (Electron never gets a chance to accept that warning). `.github/
// workflows/ci.yml` already overrides this to `http://app:8000` for exactly this reason -- for a
// local ad-hoc `cypress run` (not through the CI job), do the local-host equivalent first:
//   NEXT_PUBLIC_API_BASE_URL=http://localhost:8001 docker compose up -d frontend
// then run Cypress as normal, and `docker compose up -d frontend` again afterward (no override)
// to restore the correct real-dev-usage TLS default.
export default defineConfig({
  e2e: {
    baseUrl: process.env.CYPRESS_BASE_URL ?? "http://localhost:3000",
    supportFile: false,
    // REL-009 E9.6: Next.js/Turbopack's real dev-mode cold-compile lag (observed up to ~10-20s
    // for a route's first request per spec run in this session) can outlast the default 4000ms
    // command timeout on its own -- generous headroom here, unrelated to the real bug that used
    // to make every login test fail (see src/api/main.py's CORSMiddleware comment and
    // next.config.ts's allowedDevOrigins comment for that real root cause and fix).
    defaultCommandTimeout: 15000,
    env: {
      apiUrl: process.env.CYPRESS_API_URL ?? "http://localhost:8001",
      adminEmail: process.env.CYPRESS_ADMIN_EMAIL ?? "admin@tradingos.local",
      adminPassword: process.env.CYPRESS_ADMIN_PASSWORD ?? "dev-only-change-me",
    },
  },
});
