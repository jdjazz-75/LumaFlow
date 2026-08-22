// LumaFlow v1.0 (2026-08-07)
// Page "Lignes" des Préférences : espacement/marges des lignes de la pellicule et opacité des
// lignes inactives.

import type { Preferences } from "../lib/api";
import { PreferencesNumericRow } from "./PreferencesNumericRow";

/* Bounds mirror lumaflow/persistence/preferences.py -- kept in sync by hand
(no shared schema between the Python and TS sides yet). */
const BOUNDS = {
  row_spacing_px: [0, 40],
  row_horizontal_margin_px: [0, 40],
  vignette_margin_px: [0, 40],
  attenuated_opacity_percent: [10, 100],
} as const;

type NumericField = keyof typeof BOUNDS;

const FIELDS: { key: NumericField; label: string; suffix: string; group: "Ligne" | "Vignettes" }[] = [
  { key: "row_spacing_px", label: "Espacement entre les lignes", suffix: "px", group: "Ligne" },
  { key: "attenuated_opacity_percent", label: "Opacité des lignes inactives", suffix: "%", group: "Ligne" },
  { key: "row_horizontal_margin_px", label: "Marge latérale des lignes", suffix: "px", group: "Ligne" },
  { key: "vignette_margin_px", label: "Marge verticale", suffix: "px", group: "Vignettes" },
];

type PreferencesLinesPageProps = {
  prefs: Preferences;
  onChange: (key: NumericField, value: number) => void;
};

export function PreferencesLinesPage({ prefs, onChange }: PreferencesLinesPageProps) {
  return (
    <div className="prefs-groups">
      {(["Ligne", "Vignettes"] as const).map((group) => (
        <div key={group} className="prefs-group">
          <div className="prefs-group-title">{group}</div>
          {FIELDS.filter((field) => field.group === group).map((field) => {
            const [min, max] = BOUNDS[field.key];
            return (
              <PreferencesNumericRow
                key={field.key}
                label={field.label}
                value={prefs[field.key]}
                min={min}
                max={max}
                suffix={field.suffix}
                onChange={(value) => onChange(field.key, value)}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
