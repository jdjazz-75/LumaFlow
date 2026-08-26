// LumaFlow v1.0 (2026-08-07)
// Scénario e2e : sauvegarder une recette depuis une image, l'appliquer à une autre image et
// vérifier l'application des réglages et l'export.
import { test, expect, type Page, type Response } from "@playwright/test";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * End-to-end verification of feature 047: loading a recipe saved from one image onto a different
 * image (US1).
 *
 * Reuses the same fixture/selector conventions as tests/mvp-flow.spec.ts (dialog routes mocked via
 * page.route, navigate 127.0.0.1:8000 not localhost -- api.ts's BASE_URL hardcodes 127.0.0.1, so
 * loading the page from localhost reads as cross-origin and fails as "Failed to fetch").
 */

const FIXTURE_IMAGE_A = path.resolve(__dirname, "fixtures/zoom-overlay-large.png");
// Same aspect ratio as FIXTURE_IMAGE_A but different absolute dimensions (ratio, not absolute
// pixel size, is the compatibility criterion).
const FIXTURE_IMAGE_B_SAME_RATIO = path.resolve(__dirname, "fixtures/apply-recipe-same-ratio.png");

function tmpPath(name: string): string {
  return path.join(os.tmpdir(), `lumaflow-apply-recipe-${Date.now()}-${Math.random().toString(36).slice(2)}-${name}`);
}

function sha256File(filePath: string): string {
  return createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

/** `expectPresetCarryover` must be set whenever a preset is already active when this runs: since
2026-08-25 opening an image no longer ends at the /open response -- AppShell follows it with a
/recipe/load that re-applies the active preset to the new photo. Returning before THAT settles
leaves a caller acting on rows the carryover is about to overwrite, which is exactly how
selectNouveau's reset ended up silently undone a moment later. Waiting for the second response is
deterministic; waiting for network idle is not -- the /open request is issued only after the mocked
dialog round-trip and a React render, a gap long enough for "idle" to fire before it even starts. */
async function openTestImage(
  page: Page,
  imagePath: string,
  { expectPresetCarryover = false }: { expectPresetCarryover?: boolean } = {},
): Promise<void> {
  await page.route("**/dialogs/open-image", async (route) => {
    await route.fulfill({ json: { path: imagePath } });
  });
  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Photo" }).click();
  // Armed before the click, so neither response can be missed.
  const openResponse = page.waitForResponse(
    (r) => r.url().includes("/sessions/") && r.url().endsWith("/open") && r.request().method() === "POST",
  );
  const carryoverResponse = expectPresetCarryover
    ? page.waitForResponse((r) => r.url().includes("/recipe/load") && r.request().method() === "POST")
    : Promise.resolve(null);
  await page.getByRole("button", { name: /ouvrir/i }).first().click();
  const response = await openResponse;
  expect(response.ok()).toBeTruthy();
  await carryoverResponse;
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

/** Picks "Nouveau" in the header preset combobox, resetting every row to its neutral default on
the image currently open.

Needed since 2026-08-25: opening an image now RE-APPLIES whatever preset the combobox is showing
(bug report -- it used to keep naming a preset the freshly opened photo had never received, and
re-picking that same entry was the only way to actually get it). Saving a recipe also makes it the
active preset, so both tests below -- which save from image A before opening image B -- now find B
already carrying that recipe. A test that needs a genuinely neutral baseline on a freshly opened
image must therefore ask for one explicitly, which is what this does. */
async function selectNouveau(page: Page): Promise<void> {
  await page.locator(".preset-selector__trigger").click();
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/reset") && r.request().method() === "POST"),
    page.getByRole("button", { name: "Nouveau", exact: true }).click(),
  ]);
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
    await openTestImage(page, FIXTURE_IMAGE_B_SAME_RATIO, { expectPresetCarryover: true });
    // Explicit neutral baseline (see selectNouveau): B now inherits the just-saved recipe on open,
    // so it has to be reset for the assertions below to prove the recipe's effect rather than a
    // leftover from image A -- which is the whole point of the pre-check that follows.
    await selectNouveau(page);
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

    await openTestImage(page, FIXTURE_IMAGE_B_SAME_RATIO, { expectPresetCarryover: true });
    // Same reason as the test above: B inherits the just-saved recipe on open, so the "neutral"
    // export this test compares against has to be made genuinely neutral first -- otherwise both
    // exports below reflect the same recipe and the comparison proves nothing.
    await selectNouveau(page);
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
