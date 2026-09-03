// LumaFlow v1.0 (2026-08-07)
// Page "Vignettes" des Préférences : couleurs des aides de guidage (limites/overlays) et bornes
// min/max du zoom.

import type { Preferences } from "../lib/api";
import { PreferenceColorPicker } from "./PreferenceColorPicker";
import { PreferencesNumericRow } from "./PreferencesNumericRow";
import { t } from "../i18n";

/* Bounds mirror lumaflow/persistence/preferences.py -- kept in sync by hand
(no shared schema between the Python and TS sides yet). */
const BOUNDS = {
  zoom_min_percent: [1, 100],
  zoom_max_percent: [100, 2000],
} as const;

type NumericField = keyof typeof BOUNDS;
type ColorField = "guide_limit_color" | "guide_overlay_color";

const FIELDS: { key: NumericField; suffix: string }[] = [
  { key: "zoom_min_percent", suffix: "%" },
  { key: "zoom_max_percent", suffix: "%" },
];

type PreferencesVignettesPageProps = {
  prefs: Preferences;
  onChange: (key: NumericField | ColorField, value: number | string) => void;
};

export function PreferencesVignettesPage({ prefs, onChange }: PreferencesVignettesPageProps) {
  return (
    <div className="prefs-groups">
      <div className="prefs-group">
        <div className="prefs-group-title">{t("ui.prefs.vignettes.group.guides")}</div>
        {/* Limites de guidage (contours + poignées) et overlays de guidage (lignes/points d'aide
        dynamique) de Geometry/Cadrage/Masque Sujet/Vignette, appliquées globalement aux 4 zones
        via les tokens CSS --guide-limit-color/--guide-overlay-color (2026-08-06). */}
        <PreferenceColorPicker
          label={t("ui.prefs.vignettes.guide_limit_color")}
          value={prefs.guide_limit_color}
          onChange={(hex) => onChange("guide_limit_color", hex)}
        />
        <PreferenceColorPicker
          label={t("ui.prefs.vignettes.guide_overlay_color")}
          value={prefs.guide_overlay_color}
          onChange={(hex) => onChange("guide_overlay_color", hex)}
        />
      </div>
      <div className="prefs-group">
        <div className="prefs-group-title">{t("ui.prefs.vignettes.group.zoom")}</div>
        {FIELDS.map((field) => {
          const [min, max] = BOUNDS[field.key];
          return (
            <PreferencesNumericRow
              key={field.key}
              label={t(`ui.prefs.vignettes.${field.key}`)}
              value={prefs[field.key]}
              min={min}
              max={max}
              suffix={field.suffix}
              onChange={(value) => onChange(field.key, value)}
            />
          );
        })}
      </div>
    </div>
  );
}
