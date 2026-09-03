// LumaFlow v1.0 (2026-08-07)
// Scénario e2e des invariants UX : distinction visuelle sélection/erreur, messages d'erreur
// clairs sans jargon technique, et repères d'interface (raccourcis, indicateur d'occupation,
// libellés cohérents).
import { test, expect, type Page, type Response } from "@playwright/test";
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
 * End-to-end verification of feature 050 (UX polish): selection/error visual distinction (US1),
 * clear non-technical error messages (US2), and interface landmarks -- shortcuts, busy indicator,
 * label consistency (US3).
 *
 * FR-003's Space-bar Zoom trigger is deliberately NOT re-tested here: web/tests/mvp-flow.spec.ts
 * ("l'icône Zoom, le double-clic et la barre Espace ouvrent chacun le mode Zoom sur l'étape
 * active") already covers it end-to-end and already passes -- the original premise (no
 * handler exists) was stale by the time this feature was implemented (Filmstrip.tsx already
 * handles " "/"Spacebar", added by 046). Duplicating that coverage here would contradict this
 * session's own established non-duplication precedent (048/049).
 *
 * Reuses the same fixture/selector/dialog-mocking conventions as web/tests/mvp-flow.spec.ts.
 */

const FIXTURE_IMAGE = path.resolve(__dirname, "fixtures/zoom-overlay-large.png");

function tmpPath(name: string): string {
  return path.join(os.tmpdir(), `lumaflow-ux-invariants-${Date.now()}-${Math.random().toString(36).slice(2)}-${name}`);
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

function rowLocator(page: Page, rowLabel: string) {
  return page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: rowLabel }) });
}

// i18n phase 3 (2026-09-03) : les libellés harmonisés en français sont ceux affichés --
// "B&W" -> "N&B", "Light" -> "Lumière" (voir web/src/i18n/fr.json's row.bw.label/row.light.label).
const VISIBLE_ROW_ORDER = ["Film", "Bleach Bypass", "Color Splash", "Monochrome", "N&B", "Lumière", "Vignettage"];

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

test.describe("UX polish -- US1: état de sélection sans ambiguïté", () => {
  test("une vignette sélectionnée reste visuellement distincte d'une vignette en erreur, y compris lorsque les deux états coexistent", async ({ page }) => {
    await openTestImage(page);

    const filmRow = await navigateToRow(page, "Film");
    const target = filmRow.locator(".vignette-card").nth(1);

    // Force this vignette's server-reported status to "error" the moment it becomes selected --
    // simulating a real (if rare) thumbnail render failure on the currently active choice,
    // without touching any backend behavior (FR-007): only this one test's own response body is
    // mutated, no processing/addon code is touched.
    await page.route("**/steps/*/select", async (route) => {
      const response = await route.fetch();
      const rows = await response.json();
      const filmRowJson = rows.find((r: { label: string }) => r.label === "Film");
      const identifier = filmRowJson?.selected_vignette_identifier as string | undefined;
      if (identifier && filmRowJson.vignette_states[identifier]) {
        filmRowJson.vignette_states[identifier].status = "error";
        filmRowJson.vignette_states[identifier].detail = "Simulated render failure (test only)";
        filmRowJson.vignette_states[identifier].has_pixels = false;
      }
      await route.fulfill({ json: rows });
    });
    await target.click();

    await expect(target).toHaveClass(/vignette-card--selected/);
    await expect(target).toHaveClass(/vignette-card--error/);
    const errorSelectedBoxShadow = await target.evaluate((el) => getComputedStyle(el).boxShadow);
    expect(errorSelectedBoxShadow).toBe("none");

    // Contrast: a genuinely selected-without-error vignette on another step still gets the halo.
    const vignetteRow = await navigateToRow(page, "Vignettage");
    const cleanTarget = vignetteRow.locator(".vignette-card").nth(1);
    await cleanTarget.click();
    await expect(cleanTarget).toHaveClass(/vignette-card--selected/);
    const cleanBoxShadow = await cleanTarget.evaluate((el) => getComputedStyle(el).boxShadow);
    expect(cleanBoxShadow).not.toBe("none");
  });

  test("le même langage visuel de sélection (bordure + halo) s'applique sur toutes les étapes du workflow", async ({ page }) => {
    await openTestImage(page);

    const boxShadows: string[] = [];
    for (const label of ["Film", "Lumière", "Vignettage"]) {
      const row = await navigateToRow(page, label);
      const target = row.locator(".vignette-card").nth(1);
      await target.click();
      await expect(target).toHaveClass(/vignette-card--selected/);
      const boxShadow = await target.evaluate((el) => getComputedStyle(el).boxShadow);
      expect(boxShadow).not.toBe("none");
      boxShadows.push(boxShadow);
    }
    // Identical halo treatment across all three sampled steps -- one shared visual language, not
    // a per-step reinvention (FR-002).
    expect(new Set(boxShadows).size).toBe(1);
  });
});

test.describe("UX polish -- US2: messages d'erreur clairs, sans jargon technique", () => {
  test("l'ouverture d'un fichier introuvable affiche un message clair, sans texte d'erreur système brut", async ({ page }) => {
    await page.route("**/dialogs/open-image", async (route) => {
      await route.fulfill({ json: { path: "C:/lumaflow-050-nonexistent-open.png" } });
    });
    await page.goto("/");
    await page.locator(".header-menu").click();
    await page.getByRole("button", { name: "Photo" }).click();
    await page.getByRole("button", { name: /ouvrir/i }).first().click();

    const errorBox = page.locator(".central-work-area__error");
    await expect(errorBox).toBeVisible();
    const message = await errorBox.innerText();
    expect(message).not.toMatch(/errno|traceback|no such file or directory/i);
    expect(message.toLowerCase()).toMatch(/introuvable/);
  });

  test("un échec d'export (chemin de destination invalide) affiche un message clair, sans texte d'erreur système brut", async ({ page }) => {
    await openTestImage(page);
    const badDest = path.join(os.tmpdir(), "lumaflow-050-nonexistent-dir", "out.png");
    const response = await exportViaDialog(page, badDest, false);
    expect(response.ok()).toBeFalsy();

    const errorBox = page.locator(".central-work-area__error");
    await expect(errorBox).toBeVisible();
    const message = await errorBox.innerText();
    expect(message).not.toMatch(/errno|traceback|no such file or directory|permission denied/i);
  });

  test("le même type d'erreur (fichier/chemin introuvable) produit un message cohérent, qu'il survienne à l'ouverture d'image ou à l'export", async ({ page }) => {
    // At image open.
    await page.route("**/dialogs/open-image", async (route) => {
      await route.fulfill({ json: { path: "C:/lumaflow-050-nonexistent-a.png" } });
    });
    await page.goto("/");
    await page.locator(".header-menu").click();
    await page.getByRole("button", { name: "Photo" }).click();
    await page.getByRole("button", { name: /ouvrir/i }).first().click();
    const openMessage = await page.locator(".central-work-area__error").innerText();

    // At export, onto a real session (open the real fixture this time).
    await openTestImage(page);
    const badDest = path.join(os.tmpdir(), "lumaflow-050-nonexistent-dir-2", "out.png");
    await exportViaDialog(page, badDest, false);
    const exportMessage = await page.locator(".central-work-area__error").innerText();

    expect(openMessage).toBe(exportMessage);
  });
});

test.describe("UX polish -- US3: repères d'interface", () => {
  test("les raccourcis clavier principaux sont consultables directement depuis l'interface", async ({ page }) => {
    await openTestImage(page);
    const footerText = await page.locator(".app-footer").innerText();
    expect(footerText.toLowerCase()).toMatch(/espace/);
    expect(footerText.toLowerCase()).toMatch(/flèche/);
    expect(footerText.toLowerCase()).toMatch(/échap/);
  });

  test("un retour visuel minimal apparaît pendant l'export et se résout ensuite vers un état clair", async ({ page }) => {
    await openTestImage(page);
    await page.route("**/dialogs/export-image", async (route) => {
      await route.fulfill({ json: { path: tmpPath("busy-export.png") } });
    });
    await page.locator(".header-menu").click();
    await page.getByRole("button", { name: "Photo" }).click();
    await page.getByRole("button", { name: /exporter/i }).first().click();

    await expect(page.locator(".central-work-area__busy")).toBeVisible({ timeout: 3_000 });
    await expect(page.locator(".central-work-area__busy")).toHaveCount(0, { timeout: 15_000 });
    // Resolves to a clear state (no error), not left ambiguous (Edge Case).
    await expect(page.locator(".central-work-area__error")).toHaveCount(0);
  });

  test("les libellés des vignettes sont cohérents avec la terminologie produit sur l'ensemble des étapes (pas de fuite d'identifiant technique)", async ({ page }) => {
    await openTestImage(page);
    for (const label of VISIBLE_ROW_ORDER) {
      const row = await navigateToRow(page, label);
      const captions = await row.locator(".vignette-card__caption-text").allInnerTexts();
      expect(captions.length).toBeGreaterThan(0);
      for (const caption of captions) {
        expect(caption).not.toMatch(/_/); // no raw snake_case identifier leaking as a label
        expect(caption.trim().length).toBeGreaterThan(0);
      }
    }
  });
});
