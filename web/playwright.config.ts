// LumaFlow v1.0 (2026-08-07)
// Configuration Playwright persistante pour la suite e2e (dossier tests/, timeout 90s,
// exécution séquentielle contre un serveur lumaflow déjà lancé sur 127.0.0.1:8000).
import { defineConfig } from "@playwright/test";

/** Minimal, persistent Playwright config (2026-07-31) -- @playwright/test was already a
devDependency but had never been given a config/test dir, so every prior visual check lived in a
throwaway `.mjs` script (CLAUDE.md's documented convention) deleted after use. That convention
still applies for one-off checks; this config exists specifically for
`tests/zoom-overlay-corrections.spec.ts`, a permanent regression guard for a bug class (Geometry/
Cadrage/Masque Sujet zoom-overlay layout breaking) that has already recurred twice.

Assumes a `lumaflow` server is already running on 127.0.0.1:8000 (same assumption the ad-hoc
scripts make) -- no `webServer` block here, since this suite is meant to be run on demand against
whatever build is currently being tested, not spun up fresh per run. */
export default defineConfig({
  testDir: "./tests",
  // 60s (not the default 30s): mvp-flow.spec.ts's journeys traverse many filmstrip rows in one
  // test, each activation triggering real server-side thumbnail rendering across every vignette
  // in that row -- comfortably exceeds 30s for some addons even though each individual step is
  // fast in isolation.
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:8000",
    headless: true,
  },
});
