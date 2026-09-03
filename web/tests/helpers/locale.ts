// LumaFlow v1.0 (2026-09-03)
// Épingle la langue de l'IHM à "fr" avant chaque test e2e (i18n phase 0, garde-fou).
/* Toute la suite e2e existante sélectionne par TEXTE FRANÇAIS -- 16 occurrences réparties sur
5 fichiers (getByRole("button", { name: "Intensité" }), getByRole("switch", { name: "Geometry" }),
hasText: "Contraste"...). Depuis que Préférences > Général expose un sélecteur de langue
(i18n phase 6), la préférence persistée dans preferences.json sur la machine qui exécute la suite
peut valoir "en" -- par exemple si quelqu'un a basculé l'IHM en anglais dans une session manuelle
juste avant de lancer `npm run test:e2e`. Sans ce garde-fou, TOUTE la suite échouerait
silencieusement (des sélecteurs qui ne trouvent plus rien), sans rapport avec le changement
réellement testé -- exactement la classe de piège que documente déjà CLAUDE.md pour
localhost/127.0.0.1.

GET-then-PUT plutôt qu'un PUT direct : PUT /preferences REMPLACE l'objet persisté en entier (voir
PreferencesOut, lumaflow/api/app.py) -- il faut donc connaître les autres champs pour ne pas les
écraser à leurs valeurs par défaut. */

import type { Page } from "@playwright/test";

export async function pinFrenchLocale(page: Page): Promise<void> {
  const current = await page.request.get("/preferences").then((response) => response.json());
  if (current.ui_language === "fr") return;
  await page.request.put("/preferences", { data: { ...current, ui_language: "fr" } });
}
