// LumaFlow v1.0 (2026-08-07)
// Suite e2e de non-régression pour Geometry/Cadrage/Masque Sujet dans le Zoom (confinement,
// égalité pixel wrapper/image, centrage, précision du glissement), plus la préview réduite
// pendant le drag d'un curseur (résultat final bit-identique, pas de changement de taille du cadre).
import { test, expect, type Page, type Locator } from "@playwright/test";
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
 * Persistent regression guard for a bug class that has already recurred THREE times: Geometry/
 * Cadrage/Masque Sujet inside the Zoom overlay losing their "the whole photo stays visible, exactly
 * where you clicked" guarantee. Revalidate the whole set of invariants below, not just the point
 * you changed -- run this (`npm run test:e2e`) after any change to ZoomOverlay.tsx/.css,
 * CropCanvas.css/GeometryCanvas.css,
 * SubjectMaskStage.tsx/.css, or web/src/lib/useFittedImageBox.ts/usePanZones.tsx.
 *
 * v1 (2026-07-31) only checked "the photo fits inside its stage" -- necessary but NOT sufficient:
 * a follow-up fix (CSS Grid) satisfied that exact check while silently breaking the wrapper/image
 * pixel-equality invariant that all pointer-to-image-space coordinate math depends on (centering
 * broke, and Cadrage's actual crop output stopped matching the on-screen selection entirely). v2
 * adds the three checks that would have caught that: wrapper/image pixel equality, centering, and
 * an actual coordinate-accuracy test (drag to a known screen point, verify the result against the
 * REAL image bounding box, not just "did it stay confined"). See memory
 * geometry-cadrage-photo-overflow-grid-fix and zoom-overlay-persistent-e2e-suite.
 *
 * Uses a real ~1600x1067 fixture (tests/fixtures/zoom-overlay-large.png), not the tiny
 * deterministic_8x8.png used by backend tests -- a fixture that small never overflows any
 * container regardless of zoom level, so it can't exercise the invariants checked here (see
 * memory playwright-8x8-fixture-drag-gotcha for the same lesson learned once already).
 */

const FIXTURE_IMAGE = path.resolve(__dirname, "fixtures/zoom-overlay-large.png");
const BOX_EPSILON_PX = 1.5;

async function openTestImage(page: Page) {
  await page.route("**/dialogs/open-image", async (route) => {
    await route.fulfill({ json: { path: FIXTURE_IMAGE } });
  });
  await page.goto("/");
  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Photo" }).click();
  await page.getByRole("button", { name: /ouvrir/i }).first().click();
}

async function waitForPaneImagesLoaded(page: Page) {
  await page.waitForSelector(".zoom-overlay__pane-img", { timeout: 15_000 });
  await page.waitForFunction(
    () => {
      const imgs = Array.from(document.querySelectorAll<HTMLImageElement>(".zoom-overlay__pane-img"));
      return imgs.length > 0 && imgs.every((img) => img.complete && img.naturalWidth > 0);
    },
    { timeout: 15_000 },
  );
}

/** Waits for a correction stage's own photo to finish loading (separate <img> from the plain
compare pane's .zoom-overlay__pane-img, fetched from the auxiliary-zoom endpoint). */
async function waitForStagePhotoLoaded(page: Page, photoSelector: string) {
  await page.waitForSelector(photoSelector, { timeout: 15_000 });
  await page.waitForFunction(
    (selector) => {
      const img = document.querySelector<HTMLImageElement>(selector);
      return Boolean(img && img.complete && img.naturalWidth > 0);
    },
    photoSelector,
    { timeout: 15_000 },
  );
}

async function zoomIn(page: Page, times: number) {
  const zoomInBtn = page.locator(".zoom-overlay__optical-zoom-button").last();
  for (let i = 0; i < times; i++) {
    await zoomInBtn.click();
    await page.waitForTimeout(80);
  }
}

/** Filmstrip is a fixed 3-row sliding window (see Filmstrip.tsx), not a scroll container --
ArrowDown advances the active row one position at a time and needs a settling delay per press. */
async function navigateToRow(page: Page, rowName: string) {
  const filmstrip = page.locator(".filmstrip");
  await filmstrip.click();
  const row = page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: rowName }) });
  for (let i = 0; i < 30 && (await row.count()) === 0; i++) {
    await filmstrip.press("ArrowDown");
    await page.waitForTimeout(300);
  }
  await expect(row).toHaveCount(1);
  return row;
}

async function openFilmZoom(page: Page) {
  await openTestImage(page);
  const filmRow = page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: "Film" }) });
  await filmRow.locator(".vignette-card").first().dblclick();
  await waitForPaneImagesLoaded(page);
}

type Box = { x: number; y: number; width: number; height: number };

function expectBoxesEqual(actual: Box, expected: Box, epsilon = BOX_EPSILON_PX) {
  expect(Math.abs(actual.x - expected.x)).toBeLessThanOrEqual(epsilon);
  expect(Math.abs(actual.y - expected.y)).toBeLessThanOrEqual(epsilon);
  expect(Math.abs(actual.width - expected.width)).toBeLessThanOrEqual(epsilon);
  expect(Math.abs(actual.height - expected.height)).toBeLessThanOrEqual(epsilon);
}

async function box(locator: Locator): Promise<Box> {
  const b = await locator.boundingBox();
  expect(b).not.toBeNull();
  return b!;
}

/** Light's "Masque Sujet" panel (ergonomics revision 2026-09-24, mirroring Suppression d'objets):
 * a `CollapsibleSection` header in "Réglages manuels" (not a bare `role="switch"` any more) whose
 * body holds 4 fixed on/off zone switches plus the shared Adoucissement/Inverser controls. See
 * ZoomOverlay.tsx's renderSubjectMaskZonePanel/renderLightMaskLayer and memory
 * object-removal-addon-planned (this same pattern, applied to a second addon).
 */
async function openSubjectMaskCorrection(page: Page) {
  await page.locator(".zoom-overlay__region-controls .collapsible-section__header", { hasText: "Masque sujet" }).click();
}

async function toggleSubjectMaskZone(page: Page, n: number) {
  await page.getByRole("switch", { name: `Zone ${n}` }).click();
}

test.describe("Zoom overlay corrections -- Geometry/Cadrage/Masque Sujet", () => {
  test("Geometry: le cadre wrapper est confiné dans le stage ET pixel-identique à la photo, centré", async ({ page }) => {
    await openFilmZoom(page);
    await zoomIn(page, 8);
    await page.getByRole("switch", { name: "Géométrie" }).click();
    await waitForStagePhotoLoaded(page, ".geometry-canvas__photo");
    await page.waitForTimeout(300);

    const stageBox = await box(page.locator(".geometry-canvas__stage"));
    const wrapperBox = await box(page.locator(".geometry-canvas__photo-bounds"));
    const photoBox = await box(page.locator(".geometry-canvas__photo"));

    // Confinement (v1's original check).
    expect(photoBox.width).toBeLessThanOrEqual(stageBox.width + 1);
    expect(photoBox.height).toBeLessThanOrEqual(stageBox.height + 1);

    // v2: the wrapper used for getBoundingClientRect()-based coordinate math must be
    // pixel-identical to the actual image, not just "small enough to fit".
    expectBoxesEqual(wrapperBox, photoBox);

    // v2: centered within the stage (equal margins on both axes).
    const marginLeft = photoBox.x - stageBox.x;
    const marginRight = stageBox.x + stageBox.width - (photoBox.x + photoBox.width);
    const marginTop = photoBox.y - stageBox.y;
    const marginBottom = stageBox.y + stageBox.height - (photoBox.y + photoBox.height);
    expect(Math.abs(marginLeft - marginRight)).toBeLessThanOrEqual(BOX_EPSILON_PX);
    expect(Math.abs(marginTop - marginBottom)).toBeLessThanOrEqual(BOX_EPSILON_PX);

    // v2: the zoom slider/Ajuster + pan zones, reintroduced 2026-07-31 (reversing the 2026-07-24
    // exclusion), must now be present for Geometry.
    await expect(page.locator(".zoom-overlay__optical-zoom")).toBeVisible();
    await expect(page.locator(".zoom-overlay__optical-zoom-fit")).toBeVisible();
  });

  test("Cadrage: le cadre wrapper est confiné dans le stage ET pixel-identique à la photo, centré", async ({ page }) => {
    await openFilmZoom(page);
    await zoomIn(page, 8);
    await page.getByRole("switch", { name: "Cadrage" }).click();
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");
    await page.waitForTimeout(300);

    const stageBox = await box(page.locator(".crop-canvas__stage"));
    const wrapperBox = await box(page.locator(".crop-canvas__photo-bounds"));
    const photoBox = await box(page.locator(".crop-canvas__photo"));

    expect(photoBox.width).toBeLessThanOrEqual(stageBox.width + 1);
    expect(photoBox.height).toBeLessThanOrEqual(stageBox.height + 1);
    expectBoxesEqual(wrapperBox, photoBox);

    const marginLeft = photoBox.x - stageBox.x;
    const marginRight = stageBox.x + stageBox.width - (photoBox.x + photoBox.width);
    const marginTop = photoBox.y - stageBox.y;
    const marginBottom = stageBox.y + stageBox.height - (photoBox.y + photoBox.height);
    expect(Math.abs(marginLeft - marginRight)).toBeLessThanOrEqual(BOX_EPSILON_PX);
    expect(Math.abs(marginTop - marginBottom)).toBeLessThanOrEqual(BOX_EPSILON_PX);

    await expect(page.locator(".zoom-overlay__optical-zoom")).toBeVisible();
    await expect(page.locator(".zoom-overlay__optical-zoom-fit")).toBeVisible();
  });

  test("Cadrage: le cadrage obtenu par glissement correspond exactement au point écran utilisé (pas seulement au confinement)", async ({
    page,
  }) => {
    await openFilmZoom(page);
    await page.getByRole("switch", { name: "Cadrage" }).click();
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");
    await page.waitForTimeout(300);

    // Fit zoom (no zoomIn here) so the photo box is fully known and stable before dragging.
    const photoBox = await box(page.locator(".crop-canvas__photo"));
    const targetX = photoBox.x + photoBox.width * 0.6;
    const targetY = photoBox.y + photoBox.height * 0.55;

    const seHandle = page.locator(".crop-canvas__handle--se");
    const handleBox = await box(seHandle);
    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(targetX, targetY, { steps: 5 });
    await page.mouse.up();
    await page.waitForTimeout(200);

    // Re-read the photo box after the drag -- it must not have moved/resized as a side effect of
    // the drag itself (another way the wrapper/image mismatch bug could have manifested).
    const photoBoxAfter = await box(page.locator(".crop-canvas__photo"));
    expectBoxesEqual(photoBoxAfter, photoBox, 2);

    const frameBox = await box(page.locator(".crop-canvas__frame"));
    expectBoxesEqual(
      frameBox,
      { x: photoBox.x, y: photoBox.y, width: photoBox.width * 0.6, height: photoBox.height * 0.55 },
      4,
    );
  });

  test("Masque Sujet resets zoom to a fully-visible frame on activation, and keeps pan-zones/toolbar/wrapper==image", async ({
    page,
  }) => {
    await openTestImage(page);
    const lightRow = await navigateToRow(page, "Lumière");
    await lightRow.locator(".vignette-card").first().dblclick();
    await waitForPaneImagesLoaded(page);

    const viewportBoxBefore = await page.locator(".zoom-overlay__compare").boundingBox();
    await zoomIn(page, 8);

    // Sanity check: zooming in on the plain compare view genuinely overflows and shows pan-zones
    // -- otherwise the next assertion (mask activation re-fitting) would be vacuously true.
    const zoomedContentBox = await page.locator(".zoom-overlay__compare-content").boundingBox();
    expect(zoomedContentBox!.width).toBeGreaterThan(viewportBoxBefore!.width);
    await expect(page.locator(".zoom-overlay__pan-zone").first()).toBeVisible();

    await page.getByRole("button", { name: "Sujet" }).click();
    // Ergonomics revision 2026-09-24 (mirroring Suppression d'objets): "Masque sujet" is now a
    // collapsible panel header, not a switch -- opening it activates zone 1, which already has
    // the historical default rectangle (light.py's `_DEFAULT_MASK_POINTS`), same as before.
    await openSubjectMaskCorrection(page);
    await page.waitForTimeout(500);

    const maskContentBox = await page.locator(".zoom-overlay__compare-content").boundingBox();
    const viewportBox = await page.locator(".zoom-overlay__compare").boundingBox();
    expect(maskContentBox!.width).toBeLessThanOrEqual(viewportBox!.width + 1);
    expect(maskContentBox!.height).toBeLessThanOrEqual(viewportBox!.height + 1);

    // v2: wrapper/image pixel equality for Masque Sujet too (same underlying photoRef mechanism,
    // via ZoomOverlay.tsx's maskFractionFromPointer).
    const maskWrapperBox = await box(page.locator(".crop-canvas__photo-bounds"));
    const maskPhotoBox = await box(page.locator(".crop-canvas__photo"));
    expectBoxesEqual(maskWrapperBox, maskPhotoBox);

    // Feather/invert now live inside the panel itself (no more floating "controls" bar for Light).
    await expect(page.getByRole("switch", { name: "Zone 1" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByText("Adoucissement")).toBeVisible();
    await expect(page.locator(".zoom-overlay__optical-zoom")).toBeVisible();
  });

  test("Masque Sujet : 4 zones à bascule, sélection et désactivation indépendantes", async ({ page }) => {
    await openTestImage(page);
    const lightRow = await navigateToRow(page, "Lumière");
    await lightRow.locator(".vignette-card").first().dblclick();
    await waitForPaneImagesLoaded(page);
    await page.getByRole("button", { name: "Sujet" }).click();
    await openSubjectMaskCorrection(page);
    await page.waitForTimeout(300);

    // Zone 1 is on by default (historical rectangle); turn on Zone 2 as well.
    await expect(page.getByRole("switch", { name: "Zone 1" })).toHaveAttribute("aria-checked", "true");
    await toggleSubjectMaskZone(page, 2);
    await page.waitForTimeout(300);
    await expect(page.getByRole("switch", { name: "Zone 2" })).toHaveAttribute("aria-checked", "true");
    // Both zones' outlines are on the canvas at once.
    await expect(page.locator(".subject-mask-stage__outline")).toHaveCount(2);

    // Selecting Zone 1's label (already enabled) hands the drag handles back to it -- 4 vertices.
    await page.locator(".zoom-overlay__slider-label--clickable", { hasText: "Zone 1" }).click();
    await page.waitForTimeout(300);
    await expect(page.locator(".subject-mask-stage__vertex")).toHaveCount(4);

    // Turning Zone 2 back off removes its outline and its own switch reports off.
    await toggleSubjectMaskZone(page, 2);
    await page.waitForTimeout(300);
    await expect(page.getByRole("switch", { name: "Zone 2" })).toHaveAttribute("aria-checked", "false");
    await expect(page.locator(".subject-mask-stage__outline")).toHaveCount(1);
  });

  test("Color Splash: la zone d'application d'un intervalle réutilise le même éditeur que Masque Sujet, sans casser ses invariants", async ({
    page,
  }) => {
    await openTestImage(page);
    const colorSplashRow = await navigateToRow(page, "Color Splash");
    // First non-neutral vignette ("Rouge") -- range_1 is enabled by its preset, which is what
    // surfaces the per-range "Zone d'application" toggle in the accordion below.
    await colorSplashRow.locator(".vignette-card").nth(1).dblclick();
    await waitForPaneImagesLoaded(page);

    // The 201 zone parameters must never leak into the flat "Réglages globaux" slider list --
    // Color Splash has no SLIDER_GROUPS allow-list, so isMaskParameter is the only thing keeping
    // them out (ZoomOverlay.tsx's ungroupedSliders).
    await page.getByRole("button", { name: /Réglages globaux/i }).click();
    await expect(page.locator(".zoom-overlay__slider-label", { hasText: /sommet/i })).toHaveCount(0);

    await page.getByRole("button", { name: /Intervalle 1/i }).first().click();
    await zoomIn(page, 8);
    const zoomedContentBox = await page.locator(".zoom-overlay__compare-content").boundingBox();
    await expect(page.locator(".zoom-overlay__pan-zone").first()).toBeVisible();

    await page.getByRole("switch", { name: "Zone d'application — Intervalle 1" }).click();
    await page.waitForTimeout(500);

    // Same re-fit-on-activation guarantee as Masque Sujet (bug 2026-07-31).
    const maskContentBox = await page.locator(".zoom-overlay__compare-content").boundingBox();
    const viewportBox = await page.locator(".zoom-overlay__compare").boundingBox();
    expect(zoomedContentBox!.width).toBeGreaterThan(viewportBox!.width);
    expect(maskContentBox!.width).toBeLessThanOrEqual(viewportBox!.width + 1);
    expect(maskContentBox!.height).toBeLessThanOrEqual(viewportBox!.height + 1);

    expectBoxesEqual(
      await box(page.locator(".crop-canvas__photo-bounds")),
      await box(page.locator(".crop-canvas__photo")),
    );

    // Seeded full frame: 4 vertices, and the "Toute l'image" control this row has (Light does not).
    await expect(page.locator(".subject-mask-stage__vertex")).toHaveCount(4);
    await expect(page.locator(".subject-mask-stage__controls")).toBeVisible();
    await expect(page.getByRole("button", { name: "Toute l'image" })).toBeVisible();
    await expect(page.locator(".zoom-overlay__optical-zoom")).toBeVisible();
  });

  test("Color Splash: la couleur de remplacement est imbriquée dans son intervalle et n'apparaît que si celui-ci est actif", async ({
    page,
  }) => {
    await openTestImage(page);
    const colorSplashRow = await navigateToRow(page, "Color Splash");
    // "Substitution" -- the only preset that enables a replacement color (interval 1 only).
    await colorSplashRow.locator(".vignette-card", { hasText: "Substitution" }).dblclick();
    await waitForPaneImagesLoaded(page);

    const panel = page.locator(".zoom-overlay__panel");
    // The 3 replacement hue ranges are declared like any other, so a naive rendering would give
    // them 3 top-level sections of their own. They must stay nested instead: only the 3 intervals
    // plus "Réglages globaux" may appear at the top level.
    await expect(panel.getByRole("button", { name: /^Remplacement \d/ })).toHaveCount(0);
    for (const name of [/Intervalle 1/, /Intervalle 2/, /Intervalle 3/, /Réglages globaux/]) {
      await expect(panel.getByRole("button", { name }).first()).toBeVisible();
    }

    // Interval 1 is enabled by the preset -> both of its groups render, inside the section.
    await panel.getByRole("button", { name: /Intervalle 1/i }).first().click();
    const groups = panel.locator(".zoom-overlay__range-subgroup");
    await expect(groups).toHaveCount(2);
    const sourceGroup = groups.nth(0);
    const replacementGroup = groups.nth(1);

    // Both groups carry the same controls (2026-09-03 reorganisation); only the source selection
    // owns the spatial zone -- the replacement is confined by the interval's own.
    for (const group of [sourceGroup, replacementGroup]) {
      await expect(group).toContainText("Actif");
      await expect(group).toContainText("Adoucissement");
      await expect(group).toContainText("Intensité");
      await expect(group.locator(".color-wheel")).toBeVisible();
    }
    await expect(sourceGroup).toContainText("Zone d'application");
    await expect(replacementGroup).toContainText("Couleur de remplacement");
    await expect(replacementGroup).not.toContainText("Zone d'application");
    // The declared labels are shortened to a bare "Intensité" now that the group title carries the
    // distinction -- guards against the backend label leaking back into the panel.
    await expect(
      panel.locator(".zoom-overlay__slider-label", { hasText: /Intensité (couleur|remplacement)/ }),
    ).toHaveCount(0);

    // Interval 2 is disabled by the preset: its "Couleur" group renders (collapsed to its Actif
    // row), but a replacement for a selection that selects nothing must not be offered.
    await panel.getByRole("button", { name: /Intervalle 2/i }).first().click();
    await expect(panel.locator(".zoom-overlay__range-subgroup")).toHaveCount(3);
    await expect(
      panel.locator(".zoom-overlay__range-subgroup", { hasText: "Couleur de remplacement" }),
    ).toHaveCount(1);

    // And the replacement's own parameters must not leak into the flat global slider list.
    await page.getByRole("button", { name: /Réglages globaux/i }).click();
    await expect(
      panel.locator(".zoom-overlay__sliders > .collapsible-section")
        .filter({ hasText: "Réglages globaux" })
        .locator(".zoom-overlay__slider-label", { hasText: /remplacement/i }),
    ).toHaveCount(0);
  });
});

/**
 * Suppression d'objets (feature 100) -- same non-regression discipline as the Geometry/Cadrage/
 * Masque Sujet suite above (wrapper==image pixel equality, centering), plus zone-specific
 * invariants: enabling/disabling zones, vertex insert/delete, and a functional check that
 * Appliquer genuinely removes a distinctly-colored object. Run alongside the rest of this file
 * (`npm run test:e2e`) after any change to ZoomOverlay.tsx/.css, CropCanvas.css, or
 * RemovalToolStage.tsx/.css.
 *
 * Ergonomics revision (2026-09-24): the zone list (previously a floating "+/-"" panel over the
 * photo, up to 8 zones) moved into a `CollapsibleSection` in the "Réglages manuels" panel, with a
 * fixed MAX_REMOVAL_ZONES=4 on/off switch per zone -- opening that section (its header, not a
 * separate `role="switch"`) both reveals the zone list AND mounts the on-canvas editor
 * (RemovalToolStage), replacing the old bare `role="switch"` toggle. See ZoomOverlay.tsx's
 * renderCorrections/renderRemovalZonePanel and memory object-removal-addon-planned.
 */
async function openRemovalCorrection(page: Page) {
  await page.locator(".zoom-overlay__corrections .collapsible-section__header", { hasText: "Suppression d'objets" }).click();
}

async function toggleRemovalZone(page: Page, n: number) {
  await page.getByRole("switch", { name: `Zone ${n}` }).click();
}
const REMOVAL_FIXTURE_IMAGE = path.resolve(__dirname, "fixtures/removal-object.png");

/** Like openTestImage, but opens a given fixture and returns the session id it lifted from a real
request URL -- same technique the reduced-preview suite below already uses (response.body() has
already been found unreliable for binary payloads in this exact file; a request URL has no such
gotcha). */
async function openImageAndGetSessionId(page: Page, fixturePath: string): Promise<string> {
  let sessionId: string | null = null;
  page.on("request", (request) => {
    const match = request.url().match(/\/sessions\/([^/]+)\/open$/);
    if (match) sessionId = match[1];
  });
  await page.route("**/dialogs/open-image", async (route) => {
    await route.fulfill({ json: { path: fixturePath } });
  });
  await page.goto("/");
  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Photo" }).click();
  await page.getByRole("button", { name: /ouvrir/i }).first().click();
  await expect.poll(() => sessionId).not.toBeNull();
  return sessionId as unknown as string;
}

async function fetchAuxiliaryRemovalSliders(page: Page, sessionId: string): Promise<Record<string, number>> {
  return page.evaluate(async (id) => {
    const response = await fetch(`/sessions/${id}/zoom/auxiliary/removal`);
    const body = await response.json();
    return Object.fromEntries((body.sliders as Array<{ identifier: string; value: number }>).map((s) => [s.identifier, s.value]));
  }, sessionId);
}

/** Samples the auxiliary "after" preview's pixel color at a given fractional position, entirely
within the page context (fetch + canvas + getImageData) -- avoids Playwright's own response.body()
for a binary payload, same reasoning as hashBytesAt below. */
async function samplePixelAt(page: Page, url: string, fx: number, fy: number): Promise<[number, number, number]> {
  return page.evaluate(
    async ({ targetUrl, fx, fy }) => {
      const response = await fetch(targetUrl, { cache: "no-store" });
      const blob = await response.blob();
      const bitmap = await createImageBitmap(blob);
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(bitmap, 0, 0);
      const x = Math.min(bitmap.width - 1, Math.max(0, Math.round(fx * bitmap.width)));
      const y = Math.min(bitmap.height - 1, Math.max(0, Math.round(fy * bitmap.height)));
      const data = ctx.getImageData(x, y, 1, 1).data;
      return [data[0], data[1], data[2]] as [number, number, number];
    },
    { targetUrl: url, fx, fy },
  );
}

test.describe("Zoom overlay corrections -- Suppression d'objets", () => {
  test("le panneau apparaît sous Cadrage, dans cet ordre", async ({ page }) => {
    await openFilmZoom(page);
    const labels = page.locator(
      ".zoom-overlay__corrections .zoom-overlay__slider-label, .zoom-overlay__corrections .collapsible-section__title",
    );
    await expect(labels).toHaveText(["Géométrie", "Cadrage", "Suppression d'objets"]);
  });

  test("le cadre wrapper est confiné dans le stage ET pixel-identique à la photo, centré", async ({ page }) => {
    await openFilmZoom(page);
    await zoomIn(page, 8);
    await openRemovalCorrection(page);
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");
    await page.waitForTimeout(300);

    const stageBox = await box(page.locator(".removal-stage"));
    const wrapperBox = await box(page.locator(".crop-canvas__photo-bounds"));
    const photoBox = await box(page.locator(".crop-canvas__photo"));

    expect(photoBox.width).toBeLessThanOrEqual(stageBox.width + 1);
    expect(photoBox.height).toBeLessThanOrEqual(stageBox.height + 1);
    expectBoxesEqual(wrapperBox, photoBox);

    const marginLeft = photoBox.x - stageBox.x;
    const marginRight = stageBox.x + stageBox.width - (photoBox.x + photoBox.width);
    const marginTop = photoBox.y - stageBox.y;
    const marginBottom = stageBox.y + stageBox.height - (photoBox.y + photoBox.height);
    expect(Math.abs(marginLeft - marginRight)).toBeLessThanOrEqual(BOX_EPSILON_PX);
    expect(Math.abs(marginTop - marginBottom)).toBeLessThanOrEqual(BOX_EPSILON_PX);

    await expect(page.locator(".zoom-overlay__optical-zoom")).toBeVisible();
    await expect(page.locator(".zoom-overlay__optical-zoom-fit")).toBeVisible();
  });

  test("activer une zone dans le panneau donne 4 sommets, le glissement commit la valeur exacte côté serveur", async ({ page }) => {
    const sessionId = await openImageAndGetSessionId(page, REMOVAL_FIXTURE_IMAGE);
    const filmRow = page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: "Film" }) });
    await filmRow.locator(".vignette-card").first().dblclick();
    await waitForPaneImagesLoaded(page);
    await openRemovalCorrection(page);
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");
    await page.waitForTimeout(300);

    await toggleRemovalZone(page, 1);
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(4);

    const photoBox = await box(page.locator(".crop-canvas__photo"));
    const targetFx = 0.62;
    const targetFy = 0.58;
    const vertex = page.locator(".removal-stage__vertex").first();
    const vertexBox = await box(vertex);
    await page.mouse.move(vertexBox.x + vertexBox.width / 2, vertexBox.y + vertexBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(photoBox.x + photoBox.width * targetFx, photoBox.y + photoBox.height * targetFy, { steps: 5 });
    await page.mouse.up();
    await page.waitForTimeout(200);

    const sliders = await fetchAuxiliaryRemovalSliders(page, sessionId);
    expect(sliders["zone_0_mask_point_00_x"]).toBeCloseTo(targetFx, 2);
    expect(sliders["zone_0_mask_point_00_y"]).toBeCloseTo(targetFy, 2);
  });

  test("le milieu d'une arête ajoute un sommet, le double-clic en retire un sans jamais passer sous 3", async ({ page }) => {
    await openFilmZoom(page);
    await openRemovalCorrection(page);
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");
    await toggleRemovalZone(page, 1);
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(4);

    const midpoint = page.locator(".subject-mask-stage__midpoint").first();
    const midpointBox = await box(midpoint);
    await page.mouse.move(midpointBox.x + midpointBox.width / 2, midpointBox.y + midpointBox.height / 2);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForTimeout(200);
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(5);

    for (let i = 0; i < 3; i++) {
      await page.locator(".removal-stage__vertex").first().dblclick();
      await page.waitForTimeout(150);
    }
    // 5 -> 4 -> 3 -> refused (stays at 3, the MIN_MASK_VERTICES floor).
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(3);
  });

  test("deux zones : sélection et désactivation indépendantes", async ({ page }) => {
    await openFilmZoom(page);
    await openRemovalCorrection(page);
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");

    await toggleRemovalZone(page, 1);
    await toggleRemovalZone(page, 2);
    await expect(page.getByRole("switch", { name: "Zone 1" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByRole("switch", { name: "Zone 2" })).toHaveAttribute("aria-checked", "true");
    // Both zones' outlines are drawn (2 SVG contours on the canvas), even though only the most
    // recently enabled one (Zone 2) shows draggable vertex handles.
    await expect(page.locator(".removal-stage__zone")).toHaveCount(2);

    // Selecting Zone 1 (click its clickable label, not the switch) swaps which one shows handles.
    await page.locator(".zoom-overlay__slider-label--clickable", { hasText: "Zone 1" }).click();
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(4);

    // Turning Zone 2 off deactivates only that slot; Zone 1 stays on and keeps its own contour.
    await toggleRemovalZone(page, 2);
    await page.waitForTimeout(200);
    await expect(page.getByRole("switch", { name: "Zone 1" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByRole("switch", { name: "Zone 2" })).toHaveAttribute("aria-checked", "false");
    await expect(page.locator(".removal-stage__zone")).toHaveCount(1);
  });

  test("Appliquer retire effectivement un objet à la couleur distincte de la photo", async ({ page }) => {
    const sessionId = await openImageAndGetSessionId(page, REMOVAL_FIXTURE_IMAGE);
    const filmRow = page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: "Film" }) });
    await filmRow.locator(".vignette-card").first().dblclick();
    await waitForPaneImagesLoaded(page);
    await openRemovalCorrection(page);
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");
    await page.waitForTimeout(300);

    // The fixture's magenta disc sits at (0.5, 0.5) with radius 90px on a 1600x1067 image (~8.4%
    // of the width) -- draw a zone comfortably around it via the 4 default seed vertices, then
    // drag each corner outward so the zone fully covers the disc.
    await toggleRemovalZone(page, 1);
    const photoBox = await box(page.locator(".crop-canvas__photo"));
    const corners: Array<[number, number]> = [
      [0.5 - 0.09, 0.5 - 0.14],
      [0.5 + 0.09, 0.5 - 0.14],
      [0.5 + 0.09, 0.5 + 0.14],
      [0.5 - 0.09, 0.5 + 0.14],
    ];
    for (let i = 0; i < 4; i++) {
      const vertex = page.locator(".removal-stage__vertex").nth(i);
      const vertexBox = await box(vertex);
      await page.mouse.move(vertexBox.x + vertexBox.width / 2, vertexBox.y + vertexBox.height / 2);
      await page.mouse.down();
      const [fx, fy] = corners[i];
      await page.mouse.move(photoBox.x + photoBox.width * fx, photoBox.y + photoBox.height * fy, { steps: 5 });
      await page.mouse.up();
      await page.waitForTimeout(150);
    }

    // The bottom-panel "Appliquer" button (not the correction switch) -- disambiguate by class.
    await page.locator(".zoom-overlay__apply").click();
    await expect(page.locator(".crop-canvas__stage--preview")).toBeVisible({ timeout: 20_000 });

    const [r, g, b] = await samplePixelAt(page, `/sessions/${sessionId}/zoom/auxiliary/removal/after`, 0.5, 0.5);
    const magentaDistance = Math.sqrt((r - 230) ** 2 + (g - 30) ** 2 + (b - 220) ** 2);
    expect(magentaDistance).toBeGreaterThan(60);

    // Valider must succeed and close the Zoom overlay -- confirm_zoom keeps the auxiliary edit by
    // simply discarding its snapshot (already covered directly by the backend's own
    // test_auxiliary_zoom_removal_confirm_keeps_zones); here the closed overlay is the visible
    // signal that the flow completed without error.
    await page.locator(".zoom-overlay__confirm").click();
    await expect(page.locator(".zoom-overlay")).toHaveCount(0);
  });

  test("Réinitialiser retire toutes les zones ; Fermer (Annuler) restaure l'état précédent", async ({ page }) => {
    await openFilmZoom(page);
    await openRemovalCorrection(page);
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");
    await toggleRemovalZone(page, 1);
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(4);

    await page.locator(".zoom-overlay__reset").click();
    await page.waitForTimeout(200);
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(0);
    await expect(page.getByRole("switch", { name: "Zone 1" })).toHaveAttribute("aria-checked", "false");

    await toggleRemovalZone(page, 1);
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(4);
    // "Fermer" is this overlay's cancel action (handleCancel -> api.cancelZoom), not a separate
    // "Annuler" button -- it discards every edit made since Zoom was opened (this row's fresh zone
    // included), restoring the snapshot taken at open time.
    await page.locator(".zoom-overlay__close").click();

    // A fresh Zoom session on the same row must come back with no zone (the edit was discarded).
    await filmRowDblClick(page);
    await openRemovalCorrection(page);
    await waitForStagePhotoLoaded(page, ".crop-canvas__photo");
    await expect(page.locator(".removal-stage__vertex")).toHaveCount(0);
  });
});

async function filmRowDblClick(page: Page) {
  const filmRow = page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: "Film" }) });
  await filmRow.locator(".vignette-card").first().dblclick();
  await waitForPaneImagesLoaded(page);
}

/**
 * PERF-ZOOM-RENDER-PLAN.md étape 2: a reduced-resolution preview now fires while a "Réglages
 * manuels" slider is being actively dragged, with a full-resolution render following once it
 * settles -- two requests in flight instead of one, sequence-guarded (ZoomOverlay.tsx's
 * requestSeq/applyRenderResponse) so a late-arriving reduced response can never overwrite a
 * newer, sharper one. This is exactly the bug class this codebase has already shipped twice
 * (memory zoom-overlay-commit-race-condition-fix / appshell-export-race-condition-fix), so this
 * guards two invariants: after a rapid burst of slider changes settles, the displayed "après"
 * image must always end up bit-identical to a fresh, independent full-resolution fetch for the
 * FINAL value -- never a stale reduced-resolution or intermediate frame -- AND the compare box
 * (.zoom-overlay__compare-content) must never change size while that reduced preview is loaded
 * (2026-08-07 follow-up fix: the reduced PNG's genuinely-smaller img.naturalWidth/naturalHeight
 * was corrupting naturalSize, shrinking the whole photo to a corner mid-drag then snapping back
 * on the full-resolution response -- see afterImageIsReducedPreview in ZoomOverlay.tsx).
 */
test.describe("Zoom overlay -- aperçu réduit pendant le drag (étape 2)", () => {
  /** Hashes bytes fetched FROM WITHIN the page context via crypto.subtle.digest -- not
  Playwright's own response.body(), which the project has already found unreliable for binary
  POST responses in this exact suite. `url`
  resolves relative to the page's own origin (http://127.0.0.1:8000, per playwright.config.ts's
  baseURL -- the same origin api.ts's BASE_URL targets, so no cross-origin/CORS surprises). */
  async function hashBytesAt(page: Page, url: string): Promise<string> {
    return page.evaluate(async (targetUrl) => {
      const response = await fetch(targetUrl, { cache: "no-store" });
      const bytes = await response.arrayBuffer();
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
    }, url);
  }

  test("après un burst rapide de changements, l'image affichée finit bit-identique à un rendu plein format frais pour la DERNIÈRE valeur, ET le cadre .zoom-overlay__compare-content ne change jamais de taille", async ({
    page,
  }) => {
    await openFilmZoom(page);

    // Session id lifted from a real request URL (not response.body() -- request/response URLs
    // aren't affected by the binary-body gotcha above) so the reference fetch below targets the
    // SAME session, without inventing a test-only global.
    let sessionId: string | null = null;
    page.on("request", (request) => {
      const match = request.url().match(/\/sessions\/([^/]+)\/zoom\/parameters?$/);
      if (match) sessionId = match[1];
    });

    // Installed BEFORE the burst -- ResizeObserver fires synchronously with layout, so unlike an
    // interval poll it cannot miss a transient frame during the up-to-600ms reduced-preview
    // window. Guards the 2026-08-07 shrink-then-snap-back regression: applying a reduced-
    // resolution "après" response must update afterSrc WITHOUT ever resizing the compare box.
    const observedSizes: Array<{ width: number; height: number }> = [];
    await page.exposeFunction("__recordCompareContentSize", (width: number, height: number) => {
      observedSizes.push({ width, height });
    });
    await page.evaluate(() => {
      const el = document.querySelector(".zoom-overlay__compare-content");
      if (!el) throw new Error("wrapper introuvable");
      const record = (window as unknown as { __recordCompareContentSize: (w: number, h: number) => void })
        .__recordCompareContentSize;
      const observer = new ResizeObserver((entries) => {
        for (const entry of entries) record(entry.contentRect.width, entry.contentRect.height);
      });
      observer.observe(el);
    });

    // "Contraste" lives inside the "Tonalité" CollapsibleSection, collapsed by default (its
    // content isn't even in the DOM until expanded -- CollapsibleSection.tsx's defaultOpen=false).
    await page.getByRole("button", { name: "Tonalité" }).click();
    const contrastRow = page.locator(".zoom-overlay__slider-row", {
      has: page.locator(".zoom-overlay__slider-label", { hasText: "Contraste" }),
    });
    const contrastSlider = contrastRow.locator('input[type="range"]');
    await expect(contrastSlider).toBeVisible();

    // Rapid burst, no waits between ticks -- mirrors a real drag (each tick resets both the
    // preview-debounce and full-resolution-settle timers; neither fires until this stops).
    for (const value of [-60, -20, 20, 60, 90]) {
      await contrastSlider.fill(String(value));
    }

    // Long enough to clear FULL_RESOLUTION_SETTLE_MS (600ms) plus a real render, well short of
    // this suite's own timeouts.
    await page.waitForTimeout(4000);
    await expect(page.locator(".zoom-overlay__error")).toHaveCount(0);
    expect(sessionId).not.toBeNull();

    const afterImage = page.getByTestId("zoom-overlay-after-image");
    const displayedSrc = await afterImage.evaluate((img: HTMLImageElement) => img.src);
    const displayedHash = await hashBytesAt(page, displayedSrc);

    // Independent reference: ask the backend fresh, full-resolution, for whatever it currently
    // considers correct -- NOT a value this test hardcodes, so it stays valid even if debounce
    // timing constants change later.
    const referenceHash = await hashBytesAt(page, `http://127.0.0.1:8000/sessions/${sessionId}/zoom/after`);

    // The wrapper's box size must never have changed across the whole burst+settle window -- at
    // most one distinct size observed (zero is also fine: some Chromium builds/timings might
    // never fire an observation if nothing about layout moved at all).
    const distinctSizes = new Set(observedSizes.map((s) => `${Math.round(s.width)}x${Math.round(s.height)}`));
    expect(distinctSizes.size, `tailles observées: ${JSON.stringify(observedSizes)}`).toBeLessThanOrEqual(1);

    expect(displayedHash).toBe(referenceHash);
  });
});
