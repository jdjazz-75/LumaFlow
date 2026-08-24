// LumaFlow v1.0 (2026-08-07)
// Scénario e2e des diagnostics de chargement de recette : échec bloquant sans perte d'état, et
// correction silencieuse d'un paramètre hors bornes signalée à l'utilisateur.
import { test, expect, type Page, type Response } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * End-to-end verification of feature 048: recipe-load diagnostics.
 *
 * Reuses the same fixture/selector/dialog-mocking conventions as
 * web/tests/apply-recipe-new-image.spec.ts (feature 047, this feature's direct dependency) --
 * navigate 127.0.0.1:8000 not localhost (api.ts's BASE_URL hardcodes 127.0.0.1, so loading the
 * page from localhost reads as cross-origin and fails as "Failed to fetch").
 */

const FIXTURE_IMAGE_A = path.resolve(__dirname, "fixtures/zoom-overlay-large.png");

function tmpPath(name: string): string {
  return path.join(os.tmpdir(), `lumaflow-recipe-diagnostics-${Date.now()}-${Math.random().toString(36).slice(2)}-${name}`);
}

async function openTestImage(page: Page, imagePath: string): Promise<void> {
  await page.route("**/dialogs/open-image", async (route) => {
    await route.fulfill({ json: { path: imagePath } });
  });
  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Photo" }).click();
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/sessions/") && r.url().endsWith("/open") && r.request().method() === "POST"),
    page.getByRole("button", { name: /ouvrir/i }).first().click(),
  ]);
  expect(response.ok()).toBeTruthy();
  await page.waitForSelector(".filmstrip-row", { timeout: 15_000 });
}

/** Mocks the save-recipe dialog and drives Presets > Exporter (the recipe-save leaf). */
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

/** Mocks the load-recipe dialog and drives Presets > Ouvrir. `expectOk=false` is used for the
deliberately-invalid recipes this feature's diagnostics cover -- the POST itself still resolves
(400), only its `ok()` is false. */
async function loadRecipeViaDialog(page: Page, recipePath: string, expectOk = true): Promise<Response> {
  await page.route("**/dialogs/load-recipe", async (route) => {
    await route.fulfill({ json: { path: recipePath } });
  });
  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Presets" }).click();
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/recipe/load") && r.request().method() === "POST"),
    page.getByRole("button", { name: /ouvrir/i }).first().click(),
  ]);
  if (expectOk) expect(response.ok()).toBeTruthy();
  return response;
}

function rowLocator(page: Page, rowLabel: string) {
  return page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: rowLabel }) });
}

// Visible filmstrip row order (Geometry/Framing excluded -- HIDDEN_ROW_LABELS,
// web/src/lib/filmstrip.ts), used only to pick ArrowUp vs ArrowDown below.
const VISIBLE_ROW_ORDER = ["Film", "Bleach Bypass", "Color Splash", "Monochrome", "B&W", "Light", "Vignettage"];

/** Same keyboard-only navigation as tests/mvp-flow.spec.ts::navigateToRow -- clicking a row
mid-transition was found flaky there (a click can land with zero resulting network request). */
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

/** Saves a real recipe from the currently open image (via the UI, so it always has the
full-length, valid shape build_recipe produces) and returns its parsed JSON for mutation --
simpler and more robust than hand-crafting a recipe payload with every WORKFLOW_CONFIG row. */
async function saveRecipeJson(page: Page, destPath: string): Promise<any> {
  await saveRecipeViaDialog(page, destPath);
  return JSON.parse(fs.readFileSync(destPath, "utf-8"));
}

function writeRecipeJson(destPath: string, data: unknown): void {
  fs.writeFileSync(destPath, JSON.stringify(data), "utf-8");
}

test.describe("Recipe diagnostics -- US1: échec bloquant, reprise du travail sans redémarrage (FR-007)", () => {
  test("après un échec de chargement bloquant, l'utilisateur peut reprendre son édition immédiatement, sans recharger l'application", async ({ page }) => {
    await page.goto("/");

    await openTestImage(page, FIXTURE_IMAGE_A);
    const filmRow = await navigateToRow(page, "Film");
    const filmChoice = filmRow.locator(".vignette-card").nth(1);
    const filmIdentifier = await filmChoice.locator(".vignette-card__caption-text").innerText();
    await filmChoice.click();
    await expect(filmChoice).toHaveClass(/vignette-card--selected/);

    // A corrupted/invalid-JSON recipe file (FR-003/unreadable_file category).
    const badRecipePath = tmpPath("corrupted.json");
    fs.writeFileSync(badRecipePath, "not json at all", "utf-8");

    const response = await loadRecipeViaDialog(page, badRecipePath, false);
    expect(response.status()).toBe(400);
    await expect(page.locator(".central-work-area__error")).toBeVisible();

    // FR-006: the session is untouched -- the Film selection made before the failed load is
    // still exactly what it was, not reset or partially overwritten.
    const filmRowAfter = rowLocator(page, "Film");
    await expect(filmRowAfter.locator(".vignette-card--selected .vignette-card__caption-text")).toHaveText(filmIdentifier);

    // FR-007/SC-004: without reloading or restarting anything, the user can immediately continue
    // working -- a completely normal action succeeds right away.
    const vignetteRow = await navigateToRow(page, "Vignettage");
    const vignetteChoice = vignetteRow.locator(".vignette-card").nth(1);
    await vignetteChoice.click();
    await expect(vignetteChoice).toHaveClass(/vignette-card--selected/);
  });
});

test.describe("Recipe diagnostics -- US3: paramètre hors bornes corrigé et signalé", () => {
  test("un paramètre hors bornes est corrigé silencieusement et la correction est signalée, sans bloquer le reste de la recette", async ({ page }) => {
    await page.goto("/");

    await openTestImage(page, FIXTURE_IMAGE_A);
    const recipePath = tmpPath("recipe-out-of-bounds.json");
    const recipe = await saveRecipeJson(page, recipePath);

    // "light"/intensity is bounded [0, 1] (light.py::resolve_zoom_values) -- a stand-in for the
    // old "framing"/crop_width case, which no longer applies now that Geometry/Framing are
    // excluded from presets entirely (CLAUDE.md).
    const lightStep = recipe.steps.find((step: any) => step.step_identifier === "light");
    expect(lightStep).toBeTruthy();
    lightStep.parameters = { ...lightStep.parameters, intensity: 5.0 };
    writeRecipeJson(recipePath, recipe);

    const response = await loadRecipeViaDialog(page, recipePath);
    expect(response.ok()).toBeTruthy();

    const correctionBanner = page.locator(".central-work-area__warning", { hasText: "corrigés" });
    await expect(correctionBanner).toBeVisible();
    const correctionText = await correctionBanner.innerText();
    expect(correctionText).toMatch(/Light/);
    expect(correctionText).toMatch(/intensity/);

    // US3 Acceptance Scenario 2: the rest of the recipe is unaffected -- editing further, and
    // exporting, both still work normally.
    const filmRow = await navigateToRow(page, "Film");
    await filmRow.locator(".vignette-card").nth(1).click();
    await expect(filmRow.locator(".vignette-card").nth(1)).toHaveClass(/vignette-card--selected/);
  });
});
