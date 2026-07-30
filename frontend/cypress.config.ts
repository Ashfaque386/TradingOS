import { defineConfig } from "cypress";

// REL-009 E9.6: real E2E specs against the real running stack (frontend + app + postgres) --
// no mocked network layer. `baseUrl`/`apiUrl` default to the same values the dev-mode compose
// stack already uses (frontend:3000, app:8001) so `npx cypress run` from inside `frontend/`
// works unchanged whether run on a dev machine or inside `ci.yml`'s job.
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
