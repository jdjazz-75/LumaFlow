// LumaFlow v1.0 (2026-09-05)
// Scénario e2e du réordonnancement des lignes du workflow : ouvrir Préférences > Workflow,
// remonter "Color Splash" au-dessus de "Film" via les boutons ▲, Valider, et vérifier que la
// pellicule reflète le nouvel ordre -- Géométrie/Cadrage restant verrouillées en tête.
import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pinFrenchLocale } from "./helpers/locale";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_IMAGE = path.resolve(__dirname, "fixtures/zoom-overlay-large.png");

test.beforeEach(async ({ page }) => {
  await pinFrenchLocale(page);
});

// PUT /workflow-config est un apply EN MÉMOIRE sur le process serveur partagé -- restaurer
// l'ordre par défaut après le test, sinon les autres specs (qui supposent Film -> Bleach Bypass
// -> Color Splash -> ...) échoueraient.
test.afterEach(async ({ page }) => {
  const canonical = path.resolve(__dirname, "../../lumaflow/config/config_workflow.json");
  const draft = await page.request
    .post("/workflow-config/import", { data: { path: canonical } })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (draft) await page.request.put("/workflow-config", { data: draft }).catch(() => {});
});

async function openTestImage(page: Page): Promise<void> {
  await page.route("**/dialogs/open-image", async (route) => {
    await route.fulfill({ json: { path: FIXTURE_IMAGE } });
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

function rowCard(page: Page, label: string) {
  return page.locator(".prefs-workflow-row-card", {
    has: page.locator(".prefs-workflow-row-label", { hasText: label }),
  });
}

function filmstripRow(page: Page, label: string) {
  return page.locator(".filmstrip-row", { has: page.locator(".filmstrip-row__name", { hasText: label }) });
}

test("remonter Color Splash au-dessus de Film via Préférences > Workflow", async ({ page }) => {
  await openTestImage(page);

  await page.locator(".header-menu").click();
  await page.getByRole("button", { name: "Préférences" }).click();
  await page.getByRole("button", { name: "Workflow" }).click();
  await expect(rowCard(page, "Color Splash")).toBeVisible();

  // Color Splash part en 3e position visible (Film, Bleach Bypass, Color Splash) : deux clics ▲
  // le placent juste devant Film. Le bouton se désactive tout seul quand la ligne au-dessus est
  // Cadrage (ligne cachée, verrouillée en tête).
  const moveUp = rowCard(page, "Color Splash").getByRole("button", { name: "Monter la ligne" });
  await moveUp.click();
  await moveUp.click();
  await expect(moveUp).toBeDisabled();

  // Géométrie/Cadrage n'ont pas de commande de déplacement.
  await expect(rowCard(page, "Géométrie").getByRole("button", { name: "Monter la ligne" })).toHaveCount(0);

  const [putResponse, workflowResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/workflow-config") && r.request().method() === "PUT"),
    // handlePreferencesSaved re-fetches the open session's workflow right after Valider -- wait for
    // that, not just the PUT, before reading the filmstrip.
    page.waitForResponse((r) => /\/sessions\/[^/]+\/workflow$/.test(r.url()) && r.request().method() === "GET"),
    page.getByRole("button", { name: "Valider", exact: true }).click(),
  ]);
  expect(putResponse.ok()).toBeTruthy();
  expect(workflowResponse.ok()).toBeTruthy();

  // La pellicule (fenêtre glissante de 3 lignes, recadrée sur la 1re ligne visible après Valider)
  // reflète le nouvel ordre : Color Splash devant Film.
  await expect(page.locator(".filmstrip-row__name").first()).toHaveText("Color Splash");
  const visibleOrder = (await page.locator(".filmstrip-row__name").allInnerTexts()).map((n) => n.trim());
  expect(visibleOrder.indexOf("Color Splash")).toBeLessThan(visibleOrder.indexOf("Film"));
  // Géométrie/Cadrage restent absentes de la pellicule.
  expect(visibleOrder).not.toContain("Géométrie");
  expect(visibleOrder).not.toContain("Cadrage");

  const serverOrder = await page.request
    .get("/workflow-config")
    .then((r) => r.json())
    .then((c: { rows: { identifier: string }[] }) => c.rows.map((row) => row.identifier));
  expect(serverOrder.slice(0, 2)).toEqual(["geometry", "framing"]);
  expect(serverOrder.indexOf("color_splash")).toBeLessThan(serverOrder.indexOf("film"));
});
