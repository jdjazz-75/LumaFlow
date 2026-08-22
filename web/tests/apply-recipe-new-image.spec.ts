// LumaFlow v1.0 (2026-08-07)
// Scénario e2e : sauvegarder une recette depuis une image, l'appliquer à une autre image (même
// ratio ou ratio différent) et vérifier l'application des réglages, l'export, et l'avertissement
// de compatibilité de dimensions.
import { test, expect, type Page, type Response } from "@playwright/test";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * End-to-end verification of feature 047: loading a recipe saved from one image onto a different
 * image (US1), and the non-blocking dimension-compatibility warning when that new image's aspect
 * ratio differs from the one the recipe was authored on (US2).
 *
 * Reuses the same fixture/selector conventions as tests/mvp-flow.spec.ts (dialog routes mocked via
 * page.route, navigate 127.0.0.1:8000 not localhost -- api.ts's BASE_URL hardcodes 127.0.0.1, so
 * loading the page from localhost reads as cross-origin and fails as "Failed to fetch").
 */

const FIXTURE_IMAGE_A = path.resolve(__dirname, "fixtures/zoom-overlay-large.png");
// Same aspect ratio as FIXTURE_IMAGE_A but different absolute dimensions (ratio, not absolute
// pixel size, is the compatibility criterion).
const FIXTURE_IMAGE_B_SAME_RATIO = path.resolve(__dirname, "fixtures/apply-recipe-same-ratio.png");
// Portrait (transposed), a genuinely different aspect ratio -- must trigger the US2 warning.
const FIXTURE_IMAGE_B_DIFFERENT_RATIO = path.resolve(__dirname, "fixtures/apply-recipe-different-ratio.png");

function tmpPath(name: string): string {
  return path.join(os.tmpdir(), `lumaflow-apply-recipe-${Date.now()}-${Math.random().toString(36).slice(2)}-${name}`);
}

function sha256File(filePath: string): string {
  return createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
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

/** Mocks the load-recipe dialog and drives Presets > Ouvrir (this feature's new entry point,
Phase 2/T005 -- previously a disabled placeholder). */
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

test.describe("Recipe load -- US1: appliquer une recette sauvegardée à une nouvelle image", () => {
  test("charger une recette sauvegardée sur une nouvelle image applique ses réglages à travers toutes les étapes du workflow", async ({ page }) => {
    await page.goto("/");

    // Image A: make distinctive, non-default selections and save a recipe.
    await openTestImage(page, FIXTURE_IMAGE_A);
    const filmRowA = await navigateToRow(page, "Film");
    const filmChoice = filmRowA.locator(".vignette-card").nth(1);
    const filmIdentifier = await filmChoice.locator(".vignette-card__caption-text").innerText();
    await filmChoice.click();
    await expect(filmChoice).toHaveClass(/vignette-card--selected/);

    const vignetteRowA = await navigateToRow(page, "Vignettage");
    const vignetteChoice = vignetteRowA.locator(".vignette-card").nth(1);
    const vignetteIdentifier = await vignetteChoice.locator(".vignette-card__caption-text").innerText();
    await vignetteChoice.click();
    await expect(vignetteChoice).toHaveClass(/vignette-card--selected/);

    const recipePath = tmpPath("recipe.json");
    await saveRecipeViaDialog(page, recipePath);
    expect(fs.existsSync(recipePath)).toBe(true);

    // Image B: a genuinely different image (same aspect ratio, different absolute dimensions --
    // ratio is the criterion, not pixel size), reusing the SAME session (Photo > Ouvrir again,
    // same as opening a second
    // image in one sitting).
    await openTestImage(page, FIXTURE_IMAGE_B_SAME_RATIO);
    // Fresh image starts on the default ("Neutral") selection -- confirms the assertions below
    // are actually detecting the recipe's effect, not a leftover from image A.
    const filmRowBBefore = rowLocator(page, "Film");
    await expect(filmRowBBefore.locator(".vignette-card--selected .vignette-card__caption-text")).toHaveText("Neutral");

    await loadRecipeViaDialog(page, recipePath);

    // FR-003: the recipe's selections now appear on B, at every step, not just the one that was
    // active when the recipe was loaded.
    const filmRowB = rowLocator(page, "Film");
    await expect(filmRowB.locator(".vignette-card--selected .vignette-card__caption-text")).toHaveText(filmIdentifier);
    const vignetteRowB = await navigateToRow(page, "Vignettage");
    await expect(vignetteRowB.locator(".vignette-card--selected .vignette-card__caption-text")).toHaveText(vignetteIdentifier);
  });

  test("exporter après chargement d'une recette sur une nouvelle image produit un résultat reflétant la recette, le fichier source de la nouvelle image reste bit-identique", async ({ page }) => {
    const sourceBHashBefore = sha256File(FIXTURE_IMAGE_B_SAME_RATIO);

    await page.goto("/");

    await openTestImage(page, FIXTURE_IMAGE_A);
    const vignetteRowA = await navigateToRow(page, "Vignettage");
    await vignetteRowA.locator(".vignette-card").nth(1).click();
    await expect(vignetteRowA.locator(".vignette-card").nth(1)).toHaveClass(/vignette-card--selected/);
    const recipePath = tmpPath("recipe-export.json");
    await saveRecipeViaDialog(page, recipePath);

    await openTestImage(page, FIXTURE_IMAGE_B_SAME_RATIO);
    const neutralDest = tmpPath("b-neutral.png");
    await exportViaDialog(page, neutralDest);
    expect(fs.existsSync(neutralDest)).toBe(true);

    await loadRecipeViaDialog(page, recipePath);
    const recipeDest = tmpPath("b-with-recipe.png");
    await exportViaDialog(page, recipeDest);
    expect(fs.existsSync(recipeDest)).toBe(true);

    // FR-006/SC-004: the export genuinely reflects the recipe (differs from B's neutral export)...
    expect(sha256File(recipeDest)).not.toBe(sha256File(neutralDest));
    // ...and B's own source file on disk was never modified, at any point (FR-006).
    expect(sha256File(FIXTURE_IMAGE_B_SAME_RATIO)).toBe(sourceBHashBefore);
  });
});

test.describe("Recipe load -- US2: avertissement d'incompatibilité de dimensions", () => {
  test("charger une recette de ratio incompatible affiche un avertissement nommant l'étape concernée, sans bloquer l'édition ni l'export", async ({ page }) => {
    await page.goto("/");

    await openTestImage(page, FIXTURE_IMAGE_A);
    const recipePath = tmpPath("recipe-ratio.json");
    await saveRecipeViaDialog(page, recipePath);

    // A portrait image -- a genuinely different aspect ratio from FIXTURE_IMAGE_A (landscape).
    await openTestImage(page, FIXTURE_IMAGE_B_DIFFERENT_RATIO);
    await expect(page.locator(".central-work-area__warning")).toHaveCount(0);

    await loadRecipeViaDialog(page, recipePath);

    const warning = page.locator(".central-work-area__warning");
    await expect(warning).toBeVisible();
    // FR-004: names the concrete affected step(s), not a vague generic message.
    const warningText = await warning.innerText();
    expect(warningText).toMatch(/Geometry|Framing/);

    // Edge Case: the warning MUST NOT block continued editing...
    const filmRow = await navigateToRow(page, "Film");
    await filmRow.locator(".vignette-card").nth(1).click();
    await expect(filmRow.locator(".vignette-card").nth(1)).toHaveClass(/vignette-card--selected/);

    // ...nor export.
    const dest = tmpPath("ratio-warning-export.png");
    await exportViaDialog(page, dest);
    expect(fs.existsSync(dest)).toBe(true);

    // The warning is still visible after all of the above -- resolving it was never required.
    await expect(page.locator(".central-work-area__warning")).toBeVisible();
  });

  test("charger une recette sur une image de même ratio n'affiche aucun avertissement", async ({ page }) => {
    await page.goto("/");

    await openTestImage(page, FIXTURE_IMAGE_A);
    const recipePath = tmpPath("recipe-same-ratio.json");
    await saveRecipeViaDialog(page, recipePath);

    // Same ratio as FIXTURE_IMAGE_A, different absolute dimensions.
    await openTestImage(page, FIXTURE_IMAGE_B_SAME_RATIO);
    await loadRecipeViaDialog(page, recipePath);

    await expect(page.locator(".central-work-area__warning")).toHaveCount(0);
  });
});
