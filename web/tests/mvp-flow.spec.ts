// LumaFlow v1.0 (2026-08-07)
// Scénario e2e du parcours MVP complet : ouverture d'image, sélection à travers les étapes,
// mode Zoom (ouverture/confirmation/annulation), sauvegarde de recette et export, du début à la fin.
import { test, expect, type Page, type Response } from "@playwright/test";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pinFrenchLocale } from "./helpers/locale";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// i18n phase 0 (2026-09-03, garde-fou) -- cette suite sélectionne par texte français ; épingler
// la locale avant CHAQUE test, indépendamment du describe qui le contient (voir tests/helpers/
// locale.ts).
test.beforeEach(async ({ page }) => {
  await pinFrenchLocale(page);
});

/**
 * End-to-end verification of the primary MVP journey (feature 046): open → 6+ workflow steps →
 * optional Zoom → recipe save → export, in one continuous session through the real UI. This suite
 * is the feature's actual deliverable: every individual mechanic already existed and was
 * unit/API-tested, but no test exercised the full journey through the real frontend before this.
 *
 * Reuses the same fixture/selector conventions as tests/zoom-overlay-corrections.spec.ts (the only
 * prior Playwright spec in this repo) -- real ~1600x1067 fixture, dialog routes mocked via
 * page.route, navigate 127.0.0.1:8000 -- not localhost: api.ts's BASE_URL hardcodes 127.0.0.1, so
 * loading the page from localhost reads as cross-origin and fails as "Failed to fetch".
 *
 * Note on row count: this feature was originally specified around "6 étapes" (Geometry, Framing,
 * Film, Color Splash,
 * Light, Vignette) -- config_workflow.json has since grown to 9 rows (Bleach Bypass, Monochrome,
 * B&W added as siblings of Film), of which Geometry/Framing are hidden from the filmstrip
 * (HIDDEN_ROW_LABELS, web/src/lib/filmstrip.ts). Assertions below are written against the real,
 * current row set (queried live, never hardcoded to "6") so this suite doesn't silently go stale
 * relative to that narrative count.
 */

const FIXTURE_IMAGE = path.resolve(__dirname, "fixtures/zoom-overlay-large.png");
const UNSUPPORTED_FIXTURE = path.resolve(__dirname, "fixtures/unsupported-format.bmp");

function tmpPath(name: string): string {
  return path.join(os.tmpdir(), `lumaflow-mvp-flow-${Date.now()}-${Math.random().toString(36).slice(2)}-${name}`);
}

function sha256File(filePath: string): string {
  return createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

async function openTestImage(page: Page, imagePath: string = FIXTURE_IMAGE): Promise<void> {
  await page.route("**/dialogs/open-image", async (route) => {
    await route.fulfill({ json: { path: imagePath } });
  });
  await page.goto("/");
  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Photo" }).click();
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/sessions/") && r.url().endsWith("/open") && r.request().method() === "POST"),
    page.getByRole("button", { name: /ouvrir/i }).first().click(),
  ]);
  expect(response.ok()).toBeTruthy();
  await page.waitForSelector(".filmstrip-row", { timeout: 15_000 });
}

/** Mocks the export dialog to return `destPath` and drives the real Photo > Exporter action,
waiting for the underlying POST /export to complete. Asserts success unless expectOk is false. */
async function exportViaDialog(page: Page, destPath: string, expectOk = true): Promise<Response> {
  await page.route("**/dialogs/export-image", async (route) => {
    await route.fulfill({ json: { path: destPath } });
  });
  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Photo" }).click();
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/export") && r.request().method() === "POST"),
    page.getByRole("button", { name: /exporter/i }).first().click(),
  ]);
  if (expectOk) expect(response.ok()).toBeTruthy();
  return response;
}

/** Mocks the save-recipe dialog and drives the real Presets > Exporter action (the recipe-save
leaf -- see HeaderMenu.tsx's own comment: "Presets" group's "Exporter" leaf is onSaveRecipe). */
async function saveRecipeViaDialog(page: Page, destPath: string): Promise<Response> {
  await page.route("**/dialogs/save-recipe", async (route) => {
    await route.fulfill({ json: { path: destPath } });
  });
  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Presets" }).click();
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/recipe/save") && r.request().method() === "POST"),
    page.getByRole("button", { name: /exporter/i }).first().click(),
  ]);
  expect(response.ok()).toBeTruthy();
  return response;
}

function rowLocator(page: Page, rowLabel: string) {
  return page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: rowLabel }) });
}

// Visible filmstrip row order (Geometry/Framing excluded -- HIDDEN_ROW_LABELS,
// web/src/lib/filmstrip.ts), used only to pick ArrowUp vs ArrowDown below.
// i18n phase 3 (2026-09-03) : les libellés harmonisés en français sont ceux affichés --
// "B&W" -> "N&B", "Light" -> "Lumière" (voir web/src/i18n/fr.json's row.bw.label/row.light.label).
const VISIBLE_ROW_ORDER = ["Film", "Bleach Bypass", "Color Splash", "Monochrome", "N&B", "Lumière", "Vignettage"];

/** Filmstrip is a fixed 3-row sliding window (Filmstrip.tsx), not a scroll container -- ArrowUp/
ArrowDown advance the active row one position at a time (same pattern as
zoom-overlay-corrections.spec.ts's own navigateToRow, extended here to support both directions).
Clicking rows directly was tried and found flaky: a row mid-transition (activate/dim fade) can
silently swallow a click with no resulting network request at all, so keyboard navigation (no
pointer/hit-testing/overlay ambiguity) is the reliable choice. */
async function navigateToRow(page: Page, rowLabel: string) {
  const filmstrip = page.locator(".filmstrip");
  await filmstrip.focus();
  const row = rowLocator(page, rowLabel);

  const targetPos = VISIBLE_ROW_ORDER.indexOf(rowLabel);
  const activeRow = page.locator(".filmstrip-row").filter({ hasNot: page.locator(".filmstrip-row__dim") });
  const activeLabel = await activeRow.locator(".filmstrip-row__name").innerText();
  const activePos = VISIBLE_ROW_ORDER.indexOf(activeLabel);
  const key = targetPos >= activePos ? "ArrowDown" : "ArrowUp";

  for (let i = 0; i < 25 && (await row.count()) === 0; i++) {
    await filmstrip.press(key);
    await page.waitForTimeout(700);
  }
  await expect(row).toHaveCount(1, { timeout: 15_000 });
  return row;
}

async function waitForZoomOverlayLoaded(page: Page): Promise<void> {
  await page.waitForSelector(".zoom-overlay__pane-img", { timeout: 15_000 });
  await page.waitForFunction(
    () => {
      const imgs = Array.from(document.querySelectorAll<HTMLImageElement>(".zoom-overlay__pane-img"));
      return imgs.length > 0 && imgs.every((img) => img.complete && img.naturalWidth > 0);
    },
    { timeout: 15_000 },
  );
}

async function closeZoomOverlay(page: Page): Promise<void> {
  await page.locator(".zoom-overlay__close").click();
  await expect(page.locator(".zoom-overlay")).toHaveCount(0);
}

test.describe("MVP flow -- US1: éditer et exporter une image du début à la fin", () => {
  test("l'ouverture d'une image affiche les étapes du workflow avec une sélection par défaut visible", async ({ page }) => {
    await openTestImage(page);

    // Geometry/Framing are real pipeline steps but hidden from the filmstrip UI (see file header
    // note) -- confirm they're genuinely absent, not just off-screen in the 3-row window.
    await expect(rowLocator(page, "Géométrie")).toHaveCount(0);
    await expect(rowLocator(page, "Cadrage")).toHaveCount(0);

    // Sample a spread of visible rows (first/middle/last), not just the initially-active one, so
    // this doesn't just prove "the default active row has a default selection".
    for (const label of ["Film", "Lumière", "Vignettage"]) {
      const row = await navigateToRow(page, label);
      const selected = row.locator(".vignette-card--selected");
      await expect(selected).toHaveCount(1);
      await expect(selected.locator(".vignette-card__caption-text")).toHaveText("Neutre");
    }
  });

  test("un clic simple sur une vignette à 3 étapes différentes sélectionne et applique immédiatement, sans jamais ouvrir le Zoom", async ({ page }) => {
    await openTestImage(page);

    for (const label of ["Film", "Lumière", "Vignettage"]) {
      const row = await navigateToRow(page, label);
      const cards = row.locator(".vignette-card");
      const target = cards.nth(1); // first non-default option
      const [response] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/select") && r.request().method() === "POST"),
        target.click(),
      ]);
      expect(response.ok()).toBeTruthy();
      await expect(target).toHaveClass(/vignette-card--selected/);
      // SC-004, checked negatively after every single click.
      await expect(page.locator(".zoom-overlay")).toHaveCount(0);
    }
  });

  test("revenir à une étape déjà traitée et changer la sélection se répercute jusqu'à l'export", async ({ page }) => {
    await openTestImage(page);

    const filmRow = await navigateToRow(page, "Film");
    await filmRow.locator(".vignette-card").nth(1).click();
    await expect(filmRow.locator(".vignette-card").nth(1)).toHaveClass(/vignette-card--selected/);

    await navigateToRow(page, "Vignettage");

    // Come back to Film and pick a THIRD, different option.
    const filmRowAgain = await navigateToRow(page, "Film");
    const thirdOption = filmRowAgain.locator(".vignette-card").nth(2);
    await thirdOption.click();
    await expect(thirdOption).toHaveClass(/vignette-card--selected/);
    await expect(filmRowAgain.locator(".vignette-card").nth(1)).not.toHaveClass(/vignette-card--selected/);

    // The new choice must survive to export without redoing anything else (FR-011).
    const dest = tmpPath("revisit.png");
    await exportViaDialog(page, dest);
    expect(fs.existsSync(dest)).toBe(true);
  });

  test("l'export produit un nouveau fichier reflétant les sélections, le fichier source reste bit-identique", async ({ page }) => {
    const sourceHashBefore = sha256File(FIXTURE_IMAGE);

    await openTestImage(page);
    const neutralDest = tmpPath("neutral.png");
    await exportViaDialog(page, neutralDest);
    expect(fs.existsSync(neutralDest)).toBe(true);
    expect(path.resolve(neutralDest)).not.toBe(path.resolve(FIXTURE_IMAGE));

    // Make a visually-distinctive selection (a non-neutral Vignette preset darkens the corners)
    // and export again -- if selections genuinely reach the export, the bytes must differ from
    // the all-neutral export above (SC-002).
    const vignetteRow = await navigateToRow(page, "Vignettage");
    await vignetteRow.locator(".vignette-card").nth(1).click();
    await expect(vignetteRow.locator(".vignette-card").nth(1)).toHaveClass(/vignette-card--selected/);
    const editedDest = tmpPath("edited.png");
    await exportViaDialog(page, editedDest);
    expect(fs.existsSync(editedDest)).toBe(true);

    expect(sha256File(editedDest)).not.toBe(sha256File(neutralDest));

    // FR-009/SC-003: the source file on disk must never have been touched, at any point.
    expect(sha256File(FIXTURE_IMAGE)).toBe(sourceHashBefore);
  });
});

test.describe("MVP flow -- US2: affiner une étape via le mode Zoom", () => {
  test("l'icône Zoom, le double-clic et la barre Espace ouvrent chacun le mode Zoom sur l'étape active", async ({ page }) => {
    await openTestImage(page); // lands active on Film, which has zoom (has_zoom)
    const filmRow = rowLocator(page, "Film");

    // (a) dedicated Zoom icon ("Agrandir")
    await filmRow.locator(".vignette-card").first().locator(".vignette-card__zoom").click();
    await waitForZoomOverlayLoaded(page);
    await expect(page.locator(".zoom-overlay")).toHaveCount(1);
    await closeZoomOverlay(page);

    // (b) double-click on the vignette
    await filmRow.locator(".vignette-card").first().locator(".vignette-card__image").dblclick();
    await waitForZoomOverlayLoaded(page);
    await expect(page.locator(".zoom-overlay")).toHaveCount(1);
    await closeZoomOverlay(page);

    // (c) Space bar, with the filmstrip focused
    await page.locator(".filmstrip").focus();
    await page.locator(".filmstrip").press(" ");
    await waitForZoomOverlayLoaded(page);
    await expect(page.locator(".zoom-overlay")).toHaveCount(1);
    await closeZoomOverlay(page);
  });

  test("confirmer un ajustement Zoom l'applique à l'étape et à un export ultérieur", async ({ page }) => {
    await openTestImage(page);

    // "Intensity" scales the applied film emulation's strength -- on the default "Neutre" preset
    // (no emulation applied) it has nothing to scale, so a non-neutral preset must be selected
    // first for the slider to have any observable effect at all.
    const filmRow = rowLocator(page, "Film");
    await filmRow.locator(".vignette-card").nth(1).click();
    await expect(filmRow.locator(".vignette-card").nth(1)).toHaveClass(/vignette-card--selected/);

    const baselineDest = tmpPath("zoom-baseline.png");
    await exportViaDialog(page, baselineDest);

    await filmRow.locator(".vignette-card").nth(1).dblclick();
    await waitForZoomOverlayLoaded(page);

    // Film's sliders are grouped into collapsed "Réglages manuels" accordion sections
    // (CollapsibleSection, FILM_SLIDER_GROUPS in ZoomOverlay.tsx) -- "Intensité" is the (French)
    // group toggle button, collapsed by default; its one slider only renders once expanded, and
    // carries the addon's own raw slider label ("Intensity", English -- distinct from the
    // group's French title).
    await page.getByRole("button", { name: "Intensité" }).click();
    const intensityRow = page.locator(".zoom-overlay__slider-row", {
      // i18n phase 3 (2026-09-03) : film.py's "intensity" param declared an English label
      // ("Intensity"), harmonisé en "Intensité" (voir fr.json's param.intensity).
      has: page.locator(".zoom-overlay__slider-label", { hasText: "Intensité" }),
    });
    const slider = intensityRow.locator('input[type="range"]');
    await slider.focus();
    await slider.press("Home"); // default intensity is already 1.0 (max) for most presets, so push to minimum instead
    await page.waitForTimeout(300);

    await page.locator(".zoom-overlay__confirm").click();
    await expect(page.locator(".zoom-overlay")).toHaveCount(0);
    await expect(page.locator(".central-work-area__error")).toHaveCount(0);

    const confirmedDest = tmpPath("zoom-confirmed.png");
    await exportViaDialog(page, confirmedDest);
    expect(sha256File(confirmedDest)).not.toBe(sha256File(baselineDest));
  });

  test("annuler un ajustement Zoom restaure l'état de l'étape strictement identique à avant l'ouverture, sans changement partiel", async ({ page }) => {
    await openTestImage(page);

    // Same rationale as the "confirmer" scenario above: a non-neutral preset is needed for the
    // Intensity slider to have any observable effect to (fail to) revert.
    const filmRow = rowLocator(page, "Film");
    await filmRow.locator(".vignette-card").nth(1).click();
    await expect(filmRow.locator(".vignette-card").nth(1)).toHaveClass(/vignette-card--selected/);

    const beforeDest = tmpPath("zoom-cancel-before.png");
    await exportViaDialog(page, beforeDest);

    await filmRow.locator(".vignette-card").nth(1).dblclick();
    await waitForZoomOverlayLoaded(page);

    // Film's sliders are grouped into collapsed "Réglages manuels" accordion sections
    // (CollapsibleSection, FILM_SLIDER_GROUPS in ZoomOverlay.tsx) -- "Intensité" is the (French)
    // group toggle button, collapsed by default; its one slider only renders once expanded, and
    // carries the addon's own raw slider label ("Intensity", English -- distinct from the
    // group's French title).
    await page.getByRole("button", { name: "Intensité" }).click();
    const intensityRow = page.locator(".zoom-overlay__slider-row", {
      // i18n phase 3 (2026-09-03) : film.py's "intensity" param declared an English label
      // ("Intensity"), harmonisé en "Intensité" (voir fr.json's param.intensity).
      has: page.locator(".zoom-overlay__slider-label", { hasText: "Intensité" }),
    });
    const slider = intensityRow.locator('input[type="range"]');
    await slider.focus();
    // Default intensity is already 1.0 (max) for every preset (film.py's preset_parameters) --
    // "End" (max) would be a no-op indistinguishable from the untouched default, silently making
    // this assertion pass even if Annuler wrongly committed the change instead of discarding it
    // (found via this feature's own regression-detection exercise, 049 T006). "Home" (minimum)
    // guarantees an actual delta from default, the same reasoning the "confirmer" scenario above
    // already applies.
    await slider.press("Home");
    await page.waitForTimeout(300);

    await closeZoomOverlay(page); // cancel, not confirm

    const afterDest = tmpPath("zoom-cancel-after.png");
    await exportViaDialog(page, afterDest);
    expect(sha256File(afterDest)).toBe(sha256File(beforeDest));
  });
});

test.describe("MVP flow -- US3: sauvegarder une recette et retrouver son état", () => {
  test("sauvegarder une recette reflète l'ensemble des sélections courantes à travers toutes les étapes", async ({ page }) => {
    await openTestImage(page);

    const filmRow = await navigateToRow(page, "Film");
    const filmChoice = filmRow.locator(".vignette-card").nth(1);
    // i18n phase 3 (2026-09-03): the CAPTION can now be translated ("Round Central" ->
    // "Ronde centrée"), but the recipe's persisted `thumbnail_identifier` never is (D5) --
    // read the raw identifier from VignetteCard's `data-identifier`, not the caption's innerText,
    // or this assertion compares a French display string against an untranslated JSON field.
    const filmIdentifier = await filmChoice.getAttribute("data-identifier");
    await filmChoice.click();

    const vignetteRow = await navigateToRow(page, "Vignettage");
    const vignetteChoice = vignetteRow.locator(".vignette-card").nth(1);
    const vignetteIdentifier = await vignetteChoice.getAttribute("data-identifier");
    await vignetteChoice.click();

    const recipePath = tmpPath("recipe.json");
    await saveRecipeViaDialog(page, recipePath);
    expect(fs.existsSync(recipePath)).toBe(true);

    const recipe = JSON.parse(fs.readFileSync(recipePath, "utf-8"));
    expect(Array.isArray(recipe.steps)).toBe(true);
    expect(recipe.steps.length).toBeGreaterThan(0);

    const filmEntry = recipe.steps.find((s: { step_identifier: string }) => s.step_identifier === "film");
    const vignetteEntry = recipe.steps.find((s: { step_identifier: string }) => s.step_identifier === "vignette");
    expect(filmEntry.thumbnail_identifier).toBe(filmIdentifier);
    expect(vignetteEntry.thumbnail_identifier).toBe(vignetteIdentifier);

    // Every other step still records its (default) selection -- the recipe is a full snapshot,
    // not just a diff of what was touched.
    for (const step of recipe.steps) {
      expect(typeof step.thumbnail_identifier).toBe("string");
      expect(step.thumbnail_identifier.length).toBeGreaterThan(0);
    }
  });

  test("exporter sans modification supplémentaire après sauvegarde correspond à l'état de la recette sauvegardée", async ({ page }) => {
    await openTestImage(page);

    const filmRow = await navigateToRow(page, "Film");
    await filmRow.locator(".vignette-card").nth(1).click();
    const vignetteRow = await navigateToRow(page, "Vignettage");
    await vignetteRow.locator(".vignette-card").nth(1).click();

    const recipePath = tmpPath("recipe-roundtrip.json");
    await saveRecipeViaDialog(page, recipePath);

    const exportedDest = tmpPath("export-after-save.png");
    await exportViaDialog(page, exportedDest);

    // Independent verification path: apply the SAME saved recipe onto a
    // fresh session over the same source image and export -- must byte-for-byte match, proving
    // the recipe genuinely captured what was exported, not an approximation of it.
    const baseUrl = new URL(page.url()).origin;
    const freshSessionId = (await (await fetch(`${baseUrl}/sessions`, { method: "POST" })).json()).id as string;
    await fetch(`${baseUrl}/sessions/${freshSessionId}/open`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: FIXTURE_IMAGE }),
    });
    const loadResponse = await fetch(`${baseUrl}/sessions/${freshSessionId}/recipe/load`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: recipePath }),
    });
    expect(loadResponse.ok).toBe(true);

    const reExportedDest = tmpPath("export-from-recipe.png");
    const exportResponse = await fetch(`${baseUrl}/sessions/${freshSessionId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dest_path: reExportedDest, image_format: "PNG", force: true }),
    });
    expect(exportResponse.ok).toBe(true);

    expect(sha256File(reExportedDest)).toBe(sha256File(exportedDest));
  });
});

test.describe("MVP flow -- Polish: format non supporté (Edge Case)", () => {
  test("ouvrir un fichier non JPEG/PNG (RAW inclus) est refusé avec un message clair, sans état incohérent", async ({ page }) => {
    await page.route("**/dialogs/open-image", async (route) => {
      await route.fulfill({ json: { path: UNSUPPORTED_FIXTURE } });
    });
    await page.goto("/");
    await page.locator(".header-menu").click();
    await page.getByRole("button", { name: "Photo" }).click();
    await page.getByRole("button", { name: /ouvrir/i }).first().click();

    const errorBox = page.locator(".central-work-area__error");
    await expect(errorBox).toBeVisible();
    const message = await errorBox.innerText();
    // A clear message names the concrete accepted formats, not just an opaque code/extension.
    expect(message.toUpperCase()).toContain("JPEG");
    expect(message.toUpperCase()).toContain("PNG");
    await expect(page.locator(".filmstrip-row")).toHaveCount(0);

    // No incoherent state: a valid image can still be opened right after the rejection.
    await openTestImage(page);
    await expect(page.locator(".filmstrip-row").first()).toBeVisible();
  });
});
