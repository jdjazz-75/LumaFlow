// LumaFlow v1.0 (2026-08-07)
// Page "Général" des Préférences : couleur d'accentuation globale, dossiers (ouverture/export/
// presets) et qualité JPEG d'export par défaut.

import type { Preferences } from "../lib/api";
import { selectExportImageDirectoryDialog, selectOpenImageDirectoryDialog, selectPresetsDirectoryDialog } from "../lib/api";
import { PreferenceColorPicker } from "./PreferenceColorPicker";
import { PreferencesNumericRow } from "./PreferencesNumericRow";

export type PathField = "open_image_directory" | "export_image_directory" | "presets_directory";

const PATH_FIELDS: { key: PathField; label: string; dialog: () => Promise<{ path: string | null }> }[] = [
  { key: "open_image_directory", label: "Dossier d'ouverture des photos", dialog: selectOpenImageDirectoryDialog },
  { key: "export_image_directory", label: "Dossier d'exportation des photos", dialog: selectExportImageDirectoryDialog },
  { key: "presets_directory", label: "Dossier des presets", dialog: selectPresetsDirectoryDialog },
];

/* Bounds mirror lumaflow/persistence/preferences.py's EXPORT_JPEG_QUALITY_MIN/MAX (no shared
schema between the Python and TS sides yet, same convention as PreferencesLinesPage/
PreferencesVignettesPage). */
const EXPORT_JPEG_QUALITY_BOUNDS = [1, 100] as const;

type PreferencesGeneralPageProps = {
  prefs: Preferences;
  onBrowse: (field: PathField, dialog: () => Promise<{ path: string | null }>) => void;
  onChange: (key: "export_jpeg_quality" | "accent_color", value: number | string) => void;
};

export function PreferencesGeneralPage({ prefs, onBrowse, onChange }: PreferencesGeneralPageProps) {
  const [qualityMin, qualityMax] = EXPORT_JPEG_QUALITY_BOUNDS;
  return (
    <div className="prefs-groups">
      <div className="prefs-group">
        <div className="prefs-group-title">Apparence</div>
        {/* Couleur d'accentuation globale de l'IHM (focus, sélection, boutons d'action, sliders,
        interrupteurs, barre flottante, onglets Préférences...), 2026-08-07 -- indépendante de
        guide_limit_color/guide_overlay_color (Préférences > Vignettes), aucun état partagé. */}
        <PreferenceColorPicker
          label="Couleur d'accentuation"
          value={prefs.accent_color}
          onChange={(hex) => onChange("accent_color", hex)}
        />
      </div>
      <div className="prefs-group">
        <div className="prefs-group-title">Chemins</div>
        {PATH_FIELDS.map((field) => (
          <label key={field.key} className="prefs-row prefs-row--path">
            <span className="prefs-row-label">{field.label}</span>
            <span className="prefs-row-input prefs-row-input--path">
              <input type="text" readOnly value={prefs[field.key] ?? "(non défini)"} />
              <button type="button" className="prefs-browse-btn" onClick={() => onBrowse(field.key, field.dialog)}>
                Parcourir…
              </button>
            </span>
          </label>
        ))}
      </div>
      <div className="prefs-group">
        <div className="prefs-group-title">Export</div>
        <PreferencesNumericRow
          label="Qualité JPEG par défaut"
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
