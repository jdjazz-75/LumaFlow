// LumaFlow v1.0 (2026-09-03)
// Vérifie les budgets de longueur des deux catalogues i18n (I18N-PLAN.md §4.2/§4.3, garde-fou 1) :
// script Node autonome, pas de framework de test -- exécuter via `npm run test:i18n`.
/* Ce test ne dépend d'aucun serveur (contrairement à test:e2e) : il lit directement
web/src/i18n/{fr,en}.json. C'est le premier des deux garde-fous de longueur du plan -- un filtre
bon marché en amont ; la mesure réelle (scrollWidth/scrollHeight dans le navigateur, sur les 4
zones les plus serrées) vit dans zoom-overlay-corrections.spec.ts (garde-fou 2, Playwright).

Chaque catalogue est vérifié séparément : un dépassement en anglais seul (le cas fréquent, une
traduction plus longue que prévu) ne doit pas être masqué par le français qui, lui, tient dans son
budget. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const I18N_DIR = fileURLToPath(new URL("../src/i18n/", import.meta.url));

function loadCatalog(locale) {
  const raw = readFileSync(`${I18N_DIR}${locale}.json`, "utf-8");
  return JSON.parse(raw);
}

const CATALOGS = { fr: loadCatalog("fr"), en: loadCatalog("en") };

let failures = 0;

function fail(message) {
  failures += 1;
  console.error(`  ✗ ${message}`);
}

// --- Garde-fou 1a : chaque clé porteuse d'un `max` respecte son budget dans les DEUX locales ----
for (const [locale, catalog] of Object.entries(CATALOGS)) {
  for (const [key, entry] of Object.entries(catalog)) {
    if (key === "_meta" || entry.max === undefined) continue;
    const length = entry.t.length;
    if (length > entry.max) {
      fail(`${key} [${locale}] : ${length} caractères > budget ${entry.max} ("${entry.t}")`);
    }
  }
}

// --- Garde-fou 1b : les deux catalogues déclarent EXACTEMENT le même jeu de clés ------------------
// Une clé absente d'un des deux catalogues retomberait silencieusement sur le français (repli
// FALLBACK_LOCALE, voir i18n/index.ts) -- correct en secours, mais une divergence de clés doit être
// visible ici plutôt que découverte en changeant de langue dans l'IHM.
{
  const frKeys = new Set(Object.keys(CATALOGS.fr).filter((k) => k !== "_meta"));
  const enKeys = new Set(Object.keys(CATALOGS.en).filter((k) => k !== "_meta"));
  for (const key of frKeys) if (!enKeys.has(key)) fail(`clé "${key}" absente de en.json`);
  for (const key of enKeys) if (!frKeys.has(key)) fail(`clé "${key}" absente de fr.json`);
}

// --- Garde-fou 1c : la somme des 7 pastilles d'étape visibles tient dans la StatusBar -------------
// I18N-PLAN.md §4.2 : .status-pill-label est en white-space:nowrap dans un conteneur
// overflow-x:auto -- une pastille isolée peut dépasser son propre budget de ligne (18) sans que
// ça se voie, mais la somme des 7 doit rester sous ~95 caractères pour que la barre ne déborde
// pas visiblement sur une fenêtre de largeur usuelle. Geometry/Framing sont exclus : masqués de
// la filmstrip (et donc de la StatusBar) depuis 2026-07-24, voir filmstrip.ts's
// HIDDEN_ROW_IDENTIFIERS.
const VISIBLE_ROW_IDS = ["film", "bleach_bypass", "color_splash", "monochrome", "bw", "light", "vignette"];
const STATUS_PILL_SUM_BUDGET = 95;
for (const [locale, catalog] of Object.entries(CATALOGS)) {
  const labels = VISIBLE_ROW_IDS.map((id) => catalog[`row.${id}.label`]?.t ?? id);
  const sum = labels.reduce((total, label) => total + label.length, 0);
  if (sum > STATUS_PILL_SUM_BUDGET) {
    fail(`somme des 7 pastilles StatusBar [${locale}] : ${sum} > ${STATUS_PILL_SUM_BUDGET} (${labels.join(" · ")})`);
  }
}

if (failures > 0) {
  console.error(`\n${failures} dépassement(s) de budget i18n.`);
  process.exit(1);
}
console.log(`i18n budgets: OK (${Object.keys(CATALOGS.fr).length - 1} clés × 2 locales, somme StatusBar ≤ ${STATUS_PILL_SUM_BUDGET}).`);
