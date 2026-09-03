// LumaFlow v1.0 (2026-09-03)
// Page "Général" des Préférences : langue de l'interface, couleur d'accentuation globale,
// dossiers (ouverture/export/presets) et qualité JPEG d'export par défaut.

import type { Preferences } from "../lib/api";
import { selectExportImageDirectoryDialog, selectOpenImageDirectoryDialog, selectPresetsDirectoryDialog } from "../lib/api";
import { LOCALES, t } from "../i18n";
import { PreferenceColorPicker } from "./PreferenceColorPicker";
import { PreferencesNumericRow } from "./PreferencesNumericRow";

export type PathField = "open_image_directory" | "export_image_directory" | "presets_directory";

const PATH_FIELDS: { key: PathField; dialog: () => Promise<{ path: string | null }> }[] = [
  { key: "open_image_directory", dialog: selectOpenImageDirectoryDialog },
  { key: "export_image_directory", dialog: selectExportImageDirectoryDialog },
  { key: "presets_directory", dialog: selectPresetsDirectoryDialog },
];

/* Bounds mirror lumaflow/persistence/preferences.py's EXPORT_JPEG_QUALITY_MIN/MAX (no shared
schema between the Python and TS sides yet, same convention as PreferencesLinesPage/
PreferencesVignettesPage). */
const EXPORT_JPEG_QUALITY_BOUNDS = [1, 100] as const;

type PreferencesGeneralPageProps = {
  prefs: Preferences;
  onBrowse: (field: PathField, dialog: () => Promise<{ path: string | null }>) => void;
  onChange: (key: "export_jpeg_quality" | "accent_color" | "ui_language", value: number | string) => void;
};

export function PreferencesGeneralPage({ prefs, onBrowse, onChange }: PreferencesGeneralPageProps) {
  const [qualityMin, qualityMax] = EXPORT_JPEG_QUALITY_BOUNDS;
  return (
    <div className="prefs-groups">
      {/* Langue de l'IHM (i18n phase 6, 2026-09-03) -- en tête, avant Apparence : c'est le
      réglage qui conditionne la lecture de tous les autres. Le changement s'applique
      immédiatement (PreferencesDialog.updateField appelle setLocale), et n'est persisté dans
      preferences.json qu'à la validation ; Annuler restaure la langue d'ouverture. */}
      <div className="prefs-group">
        <div className="prefs-group-title">{t("ui.prefs.general.group.language")}</div>
        <label className="prefs-row">
          <span className="prefs-row-label">{t("ui.prefs.general.ui_language")}</span>
          <span className="prefs-row-input">
            <select
              className="prefs-select"
              value={prefs.ui_language}
              onChange={(event) => onChange("ui_language", event.target.value)}
            >
              {/* Chaque langue est nommée DANS sa propre langue, jamais traduite : un utilisateur
              arrivé par erreur dans la mauvaise locale doit reconnaître la sienne. */}
              {LOCALES.map((locale) => (
                <option key={locale.id} value={locale.id}>
                  {locale.name}
                </option>
              ))}
            </select>
          </span>
        </label>
      </div>
      <div className="prefs-group">
        <div className="prefs-group-title">{t("ui.prefs.general.group.appearance")}</div>
        {/* Couleur d'accentuation globale de l'IHM (focus, sélection, boutons d'action, sliders,
        interrupteurs, barre flottante, onglets Préférences...), 2026-08-07 -- indépendante de
        guide_limit_color/guide_overlay_color (Préférences > Vignettes), aucun état partagé. */}
        <PreferenceColorPicker
          label={t("ui.prefs.general.accent_color")}
          value={prefs.accent_color}
          onChange={(hex) => onChange("accent_color", hex)}
        />
      </div>
      <div className="prefs-group">
        <div className="prefs-group-title">{t("ui.prefs.general.group.paths")}</div>
        {PATH_FIELDS.map((field) => (
          <label key={field.key} className="prefs-row prefs-row--path">
            <span className="prefs-row-label">{t(`ui.prefs.general.${field.key}`)}</span>
            <span className="prefs-row-input prefs-row-input--path">
              <input type="text" readOnly value={prefs[field.key] ?? t("ui.prefs.general.unset")} />
              <button type="button" className="prefs-browse-btn" onClick={() => onBrowse(field.key, field.dialog)}>
                {t("ui.action.browse")}
              </button>
            </span>
          </label>
        ))}
      </div>
      <div className="prefs-group">
        <div className="prefs-group-title">{t("ui.prefs.general.group.export")}</div>
        <PreferencesNumericRow
          label={t("ui.prefs.general.export_jpeg_quality")}
          value={prefs.export_jpeg_quality}
          min={qualityMin}
          max={qualityMax}
          suffix="%"
          onChange={(value) => onChange("export_jpeg_quality", value)}
        />
      </div>
    </div>
  );
}
