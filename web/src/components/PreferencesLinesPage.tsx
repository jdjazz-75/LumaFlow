// LumaFlow v1.0 (2026-08-07)
// Page "Lignes" des Préférences : espacement/marges des lignes de la pellicule et opacité des
// lignes inactives.

import type { Preferences } from "../lib/api";
import { PreferencesNumericRow } from "./PreferencesNumericRow";
import { t } from "../i18n";

/* Bounds mirror lumaflow/persistence/preferences.py -- kept in sync by hand
(no shared schema between the Python and TS sides yet). */
const BOUNDS = {
  row_spacing_px: [0, 40],
  row_horizontal_margin_px: [0, 40],
  vignette_margin_px: [0, 40],
  attenuated_opacity_percent: [10, 100],
} as const;

type NumericField = keyof typeof BOUNDS;

const GROUPS = ["row", "vignettes"] as const;

const FIELDS: { key: NumericField; suffix: string; group: (typeof GROUPS)[number] }[] = [
  { key: "row_spacing_px", suffix: "px", group: "row" },
  { key: "attenuated_opacity_percent", suffix: "%", group: "row" },
  { key: "row_horizontal_margin_px", suffix: "px", group: "row" },
  { key: "vignette_margin_px", suffix: "px", group: "vignettes" },
];

type PreferencesLinesPageProps = {
  prefs: Preferences;
  onChange: (key: NumericField, value: number) => void;
};

export function PreferencesLinesPage({ prefs, onChange }: PreferencesLinesPageProps) {
  return (
    <div className="prefs-groups">
      {GROUPS.map((group) => (
        <div key={group} className="prefs-group">
          <div className="prefs-group-title">{t(`ui.prefs.lines.group.${group}`)}</div>
          {FIELDS.filter((field) => field.group === group).map((field) => {
            const [min, max] = BOUNDS[field.key];
            return (
              <PreferencesNumericRow
                key={field.key}
                label={t(`ui.prefs.lines.${field.key}`)}
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
