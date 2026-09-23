# Plan — Addon « Suppression d'objets » (inpainting PatchMatch) — feature 100

## Contexte

Le but est de pouvoir retirer un ou plusieurs éléments d'une photo (passant, poubelle, câble, poussière). La zone est reconstruite à partir du contenu voisin.

- La fonction est un **nouvel addon déclaratif** (Principe III).
- On y accède **comme Géométrie et Cadrage** : un interrupteur dans le panneau du Zoom des lignes visibles, placé **sous « Cadrage »**.
- Les zones se sélectionnent **comme le masque sujet de Lumière** : un polygone éditable.

Rien de ce type n'existe dans le dépôt : aucune spec, aucune maquette, aucune dépendance d'inpainting (ni cv2, ni scipy, ni skimage).

## Décisions validées

| Sujet | Décision |
|---|---|
| Algorithme | **Un seul algorithme visible : complétion multi-échelle PatchMatch** (Barnes 2009 pour le champ de correspondances, Wexler 2007 pour le vote EM de grossier à fin, la famille du « Remplissage d'après le contenu »). Une diffusion push-pull (le rôle de Telea) sert **uniquement d'initialisation interne** au niveau le plus grossier, et de repli visible si la zone est trop grande. Ni mode Telea, ni Criminisi : ce dernier est glouton, séquentiel, lent en Python pur, et surpassé par PatchMatch. |
| Dépendances | **numpy pur, sans nouvelle dépendance**, après un prototype chronométré avec verdict go/no-go. Le repli **« numba d'emblée »** est tracé dans `research.md` (R1-bis) et le moteur est structuré pour pouvoir y basculer (noyaux isolés). |
| Position dans le pipeline | **suppression → géométrie → cadrage → film → …** Les zones sont ancrées à la photo source (coordonnées normalisées), donc retoucher ensuite rotation, perspective ou cadrage ne les décale jamais et ne relance pas le calcul. Dans le panneau Zoom, l'interrupteur apparaît sous « Cadrage ». |
| Zones | **Jusqu'à 8 zones**, chacune un polygone de 32 sommets au plus, édité comme le masque sujet (glisser un sommet, « + » au milieu d'une arête, double-clic pour supprimer, 3 sommets minimum). Toutes les zones sont remplies en un seul rendu. |
| Presets | La ligne est **exclue des presets**, comme Géométrie et Cadrage. **Charger un preset réinitialise les zones**, comme aujourd'hui pour Géométrie et Cadrage : `apply_recipe` reste inchangé. |
| Seuil de performance | **≤ 12 s** pour « Appliquer » sur 12 MP avec un objet couvrant 8 % de l'image. C'est ce seuil qui déclenche le passage à numba. |

### Paramètres de l'addon

Réponse à la question « d'autres paramètres sont-ils nécessaires ? » :
- **Polygone par zone** : clés à plat `zone_{n}_mask_point_count` et `zone_{n}_mask_point_{ii}_{x|y}`, pour n de 0 à 7. L'infixe `mask_` est voulu : il permet de réutiliser tels quels `maskValuesFromById` et `isMaskParameter`.
- **`dilation`**, affiché « Marge » : de 0 à 3 % du petit côté, 0,5 par défaut. Il absorbe le halo, l'ombre et l'anticrénelage autour de l'objet ; c'est le paramètre qui compte le plus pour la qualité.
- **`feather`**, affiché « Fondu » : de 0 à 2 %, 0,3 par défaut. C'est le raccord au bord de la zone.
- **`variant`**, affiché « Autre proposition » : de 0 à 999, 0 par défaut. C'est la graine du tirage aléatoire ; le bouton l'incrémente puis applique.
- Automatiques : taille de patch et zone de contexte, déduites de la résolution.
- Pas d'« Inverser ». La clé `intensity` est interdite (collision avec la sonde des valeurs par défaut, `auxiliary_zoom_pure_default_values`).
- Reporté en v2 : exclure des zones comme sources possibles.

## Architecture

### Moteur : `lumaflow/addons/inpainting/`

C'est un package normal, placé hors de `builtin/`, donc jamais scanné par le chargeur d'addons.

- `engine.py` est le pilote : regroupement des zones, zones de contexte, pyramide, programme EM, initialisation push-pull, suréchantillonnage du champ de correspondances, composition finale.
- `kernels.py` contient les noyaux numpy chauds regroupés dans un `KernelBackend` (`patch_cost`, `patchmatch_iteration`, `vote`). C'est le **point de bascule vers numba** : un `kernels_numba.py` pourrait les remplacer sans toucher au pilote.
- Algorithme :
  1. Construire le masque des trous par zone avec PIL : remplissage du polygone, puis contour épais `line(width=2r+1, joint="curve")`, puis un disque à chaque sommet. On obtient une dilatation par disque exacte, indépendante de la résolution, avec au moins 1 px d'emprise.
  2. Regrouper les zones en groupes aux boîtes disjointes. Chaque groupe a sa propre zone de contexte (marge d'environ 0,75 × la boîte, 4 % du petit côté au minimum), élargie si les sources valides manquent.
  3. Construire la pyramide par moyennes 2×2 (max-pool pour le trou), avec des patchs 7×7.
  4. Au niveau le plus grossier : remplissage push-pull, puis champ de correspondances aléatoire.
  5. À chaque niveau, alterner propagation « jump-flood » vectorisée, recherche aléatoire, et vote pondéré (poids `exp(-coût/2σ²)` × confiance près du bord).
  6. Au-delà d'un plafond de cibles (`_EM_MAX_TARGETS`, réglé par le prototype), ne plus faire que suréchantillonner le champ puis voter une fois, en lisant directement les pixels uint8 à pleine résolution.
  7. Composer : seuls les pixels du trou et de la bande de fondu sont écrits ; **tout le reste est identique au bit près**.
  8. Tirage aléatoire déterministe : `default_rng(SeedSequence([variant, groupe, niveau, SALT]))`.

### Addon : `lumaflow/addons/builtin/object_removal.py`

- `identifier="object_removal"`, `category="object_removal"`, un seul preset `neutral`.
- `remove_objects(image, params)` :
  - sans zone valide, renvoie `image` tel quel ;
  - ne mute jamais l'entrée ;
  - lit les zones défensivement (`math.isfinite`, bornes, booléens rejetés).
- `resolve_zoom_values` complet (523 clés).
- Les paramètres de zone sont `transient` (garde-fou supplémentaire).
- Descriptions générées par `_zone_parameter_descriptions(n)`, sur le modèle de [color_splash.py](lumaflow/addons/builtin/color_splash.py).
- Rasterisation calquée sur `_polygon_mask` et `_box_blur` de [light.py:755-773](lumaflow/addons/builtin/light.py#L755-L773). Ces fonctions sont **copiées** : les imports entre addons ne fonctionnent pas.

### Intégration backend

- **[config_workflow.json](lumaflow/config/config_workflow.json)** : nouvelle ligne `removal` (catégorie `object_removal`, preset `neutral`) **en première position**.
- **[workflow.py](lumaflow/config/workflow.py)**, source unique des lignes épinglées :
  - `PINNED_LEADING_ROW_IDENTIFIERS = ("removal","geometry","framing")`, ordonné.
  - `load_canonical_workflow_config()`.
  - `normalize_pinned_leading_rows(config, reference)` : pure et en mémoire. Elle insère les lignes épinglées manquantes dans une config ancienne, par exemple un export utilisateur ou `config_workflow-new1.json`. Une config sans aucune ligne épinglée reste inchangée.
- **[session.py](lumaflow/api/session.py)** :
  - `_resolve_initial_workflow_config()` normalise ses deux branches, en mémoire seulement : l'invariant « Valider n'écrit jamais sur disque » est respecté.
  - `_HIDDEN_ROW_IDENTIFIERS` est dérivé du tuple épinglé.
  - Nouveau `set_auxiliary_zoom_parameters(session, row, updates)` : écriture groupée, instantané au premier écrit, sans rendu. Le singulier existant délègue à cette fonction.
  - Nouveau `render_auxiliary_after(session, row)`, qui vaut `render_full_resolution(upto_exclusive=index+1)` et alimente le cache position 0 réutilisé par `/zoom/after`.
- **[app.py](lumaflow/api/app.py)** :
  - `_LEADING_ROW_IDENTIFIERS` devient le tuple importé. `_validate_workflow_row_identity` exige désormais **l'ordre exact**, alors qu'il ne vérifiait qu'un ensemble. La catégorie reste `leading_rows_locked`, avec un message mis à jour.
  - `import_workflow_config_endpoint` normalise la config avant de la valider.
  - Nouveaux endpoints `POST /sessions/{id}/zoom/auxiliary/{row}/parameters` (`{updates:[…]}` → 204) et `GET /sessions/{id}/zoom/auxiliary/{row}/after` (PNG).
- **[recipe.py](lumaflow/persistence/recipe.py)** : `EXCLUDED_STEP_IDENTIFIERS = {"removal","geometry","framing"}`.
- **Vérifiés sans changement** : `precompute_row_before` (retour immédiat pour step 0), `_compute_vignette_states`, `reorder_session_pipeline`, `open_zoom`/`confirm_zoom`/`cancel_zoom`, `batch_runs` (étape neutre), `apply_recipe`.

### Intégration frontend

- **[api.ts](web/src/lib/api.ts)** : `setAuxiliaryZoomParameters` et `auxiliaryZoomAfterUrl`.
- **[filmstrip.ts](web/src/lib/filmstrip.ts)** : ajouter `"removal"` à `HIDDEN_ROW_IDENTIFIERS`. Cela couvre automatiquement Filmstrip, StatusBar, la première ligne visible d'AppShell, et PreferencesWorkflowPage (3 cartes épinglées sans ▲/▼).
- **Nouveau `web/src/lib/removalZones.ts`** (fonctions pures) :
  - `MAX_REMOVAL_ZONES=8` ;
  - `removalValuesFromById` / `removalValuesToUpdates`, qui réutilisent `maskValuesFromById` avec le préfixe `zone_N_` et renumérotent les zones à la suppression ;
  - `seedZone(n)` : rectangle de 0,4 à 0,6, légèrement décalé à chaque zone ;
  - `insertMidpoint`, `removeVertex` ;
  - `polygonArea`, pour l'indice « grande zone ».
- **Nouveau `web/src/lib/useRemovalZones.ts`** : état remonté, partagé par la scène et le panneau, comme `maskPoints`.
- **Nouveau `RemovalToolStage.tsx` + `.css`** :
  - Suit le modèle de scène de GeometryToolStage/CropToolStage : `forwardRef {reset, apply}`, avec `useFittedImageBox`, `usePanZones`, `ZoomToolbar`, et les classes `crop-canvas__*`. Le dimensionnement est calculé en JS, ce qui garantit wrapper == image.
  - Photo de fond : la **source** (le « avant » auxiliaire de `removal`).
  - Zones en SVG, en coordonnées pixel de la source : remplissage ambre translucide, zones inactives atténuées, clic pour sélectionner, poignées sommet et « + » sur la zone active.
  - Marge et fondu prévisualisés par des traits arrondis. Contour en `vector-effect="non-scaling-stroke"`, sans dasharray (piège connu).
  - `apply()` affiche l'aperçu de `/zoom/auxiliary/removal/after` ; un clic reprend l'édition.
  - Pendant le calcul, un voile « Calcul du remplissage… » s'affiche et les boutons sont désactivés.
  - Sans zone, un indice non bloquant s'affiche ; aucune zone n'est créée automatiquement.
  - Exporte aussi `RemovalZoneControls` pour le panneau : puces « Zone 1…N », « Ajouter une zone » (désactivé à 8), « Supprimer la zone », curseurs Marge et Fondu (enregistrés au relâchement), « Autre proposition ».
  - [SubjectMaskStage.tsx](web/src/components/SubjectMaskStage.tsx) **n'est pas modifié** : on ne réutilise que ses fonctions pures, pour ne faire courir aucun risque à Lumière et Color Splash.
- **[ZoomOverlay.tsx](web/src/components/ZoomOverlay.tsx)** :
  - `CorrectionKind` accepte `"removal"`, et `CORRECTION_KINDS = ["geometry","framing","removal"]`.
  - Ajouter `removalAux` et `loadRemovalAux()`, sur le modèle de `loadFramingAux`.
  - Enregistrer les modifications via `trackCommit(api.setAuxiliaryZoomParameters(...))`.
  - Brancher la nouvelle correction dans `handleCorrectionApply`, `handleReset` (retire toutes les zones), le montage de la scène et `renderCorrections()` (contrôles de zones sous l'interrupteur).
  - **Corriger deux défauts existants au passage** :
    - `toggleCorrection` ne vide pas `activeMask` ;
    - la vue avant/après n'est rechargée qu'à l'ouverture du Zoom ([:650-651](web/src/components/ZoomOverlay.tsx#L650-L651)). Correctif : quand on désactive une correction qui a été modifiée, recharger `/zoom/before` puis `/zoom/after`, l'un après l'autre.
- **ZoomOverlay.css** : ajouter `.removal-stage__busy` et `.removal-stage__hint` à la table des z-index (l. 10-26).
- **i18n**, dans fr.json **et** en.json, avec budgets `max` :
  - `zoom.correction.removal` : « Suppression d'objets » / « Object removal » ;
  - `row.removal.label` et `row.removal.description` ;
  - `ui.removal.{zone, add_zone, delete_zone, margin, feather, variant, empty_hint, max_zones, computing, preview_badge, large_zone_hint}`.

## Étapes de réalisation

1. **Gouvernance** :
   - `/speckit.constitution` : passage de 1.6.0 à **1.7.0 (MINOR)**. La contrainte produit liste les 10 lignes réelles, dont 3 masquées épinglées dans l'ordre suppression → géométrie → cadrage.
   - `/speckit.specify` : dossier `specs/100-addon-object-removal-v1/`. Vérifier le préfixe 100 (mémoire spec-prefix-preservation), puis `/speckit.clarify`.
2. **Prototype (Phase 0 de `/speckit.plan`)** :
   - Créer le moteur directement à son emplacement définitif, plus `benchmarks/bench_object_removal.py` (même conventions que `bench_pipeline.py` : minimum sur 5 passes, compteurs d'évaluations, A/B alterné, `tracemalloc`).
   - Cas mesurés : 480 px, 1600 px, 12 MP et 24 MP ; trous de 2 %, 8 %, deux zones, et une zone fine.
   - Images : synthétique (texture, ligne droite, disque magenta), plus 3 RAW réels de `../exemples/raw/`, relus par l'utilisateur.
   - **Seuils GO** :

     | Cas | Cible |
     |---|---|
     | 480 px, trou 2 % | ≤ 0,5 s |
     | 480 px, trou 8 % | ≤ 1 s |
     | 12 MP, trou 2 % | ≤ 6 s |
     | **12 MP, trou 8 %** | **≤ 12 s** |
     | 24 MP, trou 8 % | ≤ 25 s et ≤ 1,5 Go de mémoire |

   - Contrôles qualité :
     - Q1 : plus de magenta, et moyenne et dispersion proches de l'anneau autour du trou ;
     - Q2 : la ligne continue à ±3 px ;
     - Q3 : résultat déterministe ;
     - Q4 : les pixels hors zone sont identiques au bit près ;
     - Q5 : les photos réelles sont validées par l'utilisateur.
   - Verdicts :
     - **TUNE** si le résultat est à moins de 1,5× des seuils : une passe d'optimisation (coût incrémental, patch sous-échantillonné, programme EM, plafond de cibles), puis nouvelle mesure ;
     - **NO-GO** sinon : passage à numba, après retour vers l'utilisateur.
   - Traces dans `research.md` :
     - R1 : mesures et verdict ;
     - R1-bis : repli numba, avec déclencheurs, `pyproject.toml`, compatibilité numba avec numpy 2.4.2 et Python 3.13 sur win_amd64 (risque de rétrogradation de numpy), mise en cache JIT et préchauffage, justification au titre du Principe V.
3. **Moteur et addon**, plus tests unitaires, backend seul.
4. **Intégration backend** : ligne de config, lignes épinglées et normalisation, validation de l'ordre, deux endpoints, exclusion des presets, correction des tests existants.
5. **Frontend** : api.ts, filmstrip.ts, removalZones et useRemovalZones, RemovalToolStage, câblage de ZoomOverlay et les deux correctifs, i18n.
6. **E2E, build, vérification visuelle** (`checklists/visual-verification.md`, Principe VI).
7. **Documentation** :
   - `docs/fonctionnalites.html` et `docs/en/features.html` (§2, §3.4 « Corrections croisées », §3.9) ;
   - `README.md` ;
   - `CLAUDE.md` : ajouter `RemovalToolStage.css`/`.tsx` à la liste de non-régression et au périmètre de `npm run test:e2e` ;
   - une mémoire ;
   - **relancer le serveur**.

## Tests existants à adapter (décalage d'index dû à la nouvelle ligne 0)

- `tests/test_default_workflow.py:29-57` : 10 lignes, `removal` en tête.
- `tests/test_recipe_model.py:149` : ensemble d'exclusion.
- `tests/test_api_session_wiring.py` : `:1579/1589` (Film supposé à l'index 2) et `:2866` (`after[:3]`). Les accès par index (`steps/1`, `zoom/0`, etc.) passent désormais par une recherche par identifiant.
- `tests/test_addon_loader.py` : résolution de `object_removal`.
- `web/tests/mvp-flow.spec.ts:156` (ligne absente) et `web/tests/workflow-row-reorder.spec.ts:71,96` (`slice(0,3)`, pas de ▲/▼ sur la carte suppression).

## Vérification

- **Unitaires** :
  - `tests/test_inpainting_engine.py` : coût de patch comparé à une version naïve, la propagation ne dégrade jamais le coût, le vote avec le champ identité rend l'image, sources toujours valides, résultat indépendant du découpage mémoire, push-pull sans trou, déterminisme.
  - `tests/test_addon_object_removal.py` :
    - le cas neutre renvoie le même objet ; aucune mutation de l'entrée ;
    - variant identique → sortie identique ; variant+1 → sortie différente dans le trou uniquement ;
    - hors zone identique au bit près ;
    - disque magenta supprimé et ligne prolongée ;
    - union de plusieurs zones ; une 9ᵉ zone est ignorée ;
    - polygones dégénérés, NaN/inf/booléens, zone couvrant toute l'image ;
    - indépendance à la résolution (480 px contre 1600 px) ;
    - `resolve_zoom_values` et forme de la description ;
    - test `@pytest.mark.perf`.
- **API**, dans `tests/test_api_session_wiring.py` :
  - endpoint groupé : 204, sans rendu, instantané ;
  - Annuler restaure, Valider conserve ;
  - l'aperçu auxiliaire vaut `render_full_resolution(upto=1)` ;
  - cache : zones calculées une seule fois, et une retouche Film ou Géométrie ne relance pas la suppression ;
  - exclusion des presets ;
  - migration d'une config ancienne au démarrage et à l'import (`tests/fixtures/workflow_config/legacy_without_removal.json`, fichier inchangé sur disque) ;
  - `leading_rows_locked` si l'ordre n'est pas respecté.
  - Commande : `pytest`, puis `pytest -m perf`.
- **E2E** : nouveau bloc « Suppression d'objets » dans [zoom-overlay-corrections.spec.ts](web/tests/zoom-overlay-corrections.spec.ts), en locale FR.
  - Géométrie, Cadrage puis Suppression d'objets, dans cet ordre.
  - La photo reste dans la scène, wrapper == image, centrée.
  - Ajouter une zone donne 4 sommets ; un glisser à zoom > 100 % donne la valeur attendue à ±0,003 près via `GET /zoom/auxiliary/removal`.
  - « + » ajoute un sommet ; le double-clic en retire un, jamais sous 3.
  - Deux zones : sélection et suppression.
  - Test fonctionnel sur la nouvelle fixture `web/tests/fixtures/removal-object.png` (1600×1067, disque magenta) : on dessine une zone, puis Appliquer ; plus de magenta échantillonné, que ce soit via `page.evaluate` sur un canvas ou via Valider.
  - Réinitialiser et Annuler.
  - Pas de débordement des nouveaux libellés.
- **Commandes** :
  - `npm run test:i18n` ;
  - `npm run build`, puis serveur sur **http://127.0.0.1:8000** (pas localhost) et `npm run test:e2e` ;
  - après toute modification de `lumaflow/api/`, vérifier au préalable avec `curl` que le serveur sert le nouveau comportement (piège de `--reload`).
- **Visuel** : captures Playwright de la scène et du panneau, plus les invariants des scènes Géométrie, Cadrage et Masque sujet (non-régression).

## Risques assumés

- **Aperçu et export ne sont pas identiques au pixel près.** Vignettes et aperçu remplissent la zone à 480 px, alors qu'Export et Zoom le font à pleine résolution : même structure, texture fine différente. C'est documenté dans la spec.
- **La latence se reporte sur les autres actions.** Avec un cache froid, ouvrir le Zoom sur n'importe quelle ligne, la scène Géométrie/Cadrage (qui inclut maintenant le résultat de la suppression) ou l'export paie une fois le calcul ; le cache position 0 sert ensuite.
- **Le calcul occupe un worker.** Un « Appliquer » long bloque un worker du threadpool pendant 5 à 12 s ; le voile et les boutons désactivés couvrent l'UX, et un verrou « en cours » par position de cache est un durcissement optionnel.
- **Les zones se dessinent sur la photo non redressée.** C'est voulu : elles sont ancrées à la source. Une indication dans le panneau et la documentation l'expliquent.
- **Charger un preset efface les zones** (décision validée). Le signaler dans la documentation.
- **Hors périmètre** : `light.py:_read_float` laisse passer NaN. C'est à signaler, avec un correctif séparé.
