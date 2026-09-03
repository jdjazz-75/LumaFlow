// LumaFlow v1.0 (2026-08-07)
// Ligne de champ numérique réutilisable (label + input + stepper haut/bas + unité), partagée par
// les pages Lignes/Vignettes des Préférences.

import { ChevronDownIcon, ChevronUpIcon } from "./icons";
import { t } from "../i18n";

/** A labeled number field + up/down stepper + unit suffix -- shared by PreferencesLinesPage and
PreferencesVignettesPage (2026-08-05 Préférences reorganization), extracted from what used to be
the single PreferencesGeneralPage's per-field row so the two pages don't duplicate this markup. */
type PreferencesNumericRowProps = {
  label: string;
  value: number;
  min: number;
  max: number;
  suffix: string;
  onChange: (value: number) => void;
};

export function PreferencesNumericRow({ label, value, min, max, suffix, onChange }: PreferencesNumericRowProps) {
  function clamp(next: number): number {
    return Math.max(min, Math.min(max, next));
  }

  return (
    <label className="prefs-row">
      <span className="prefs-row-label">{label}</span>
      <span className="prefs-row-input">
        <input type="number" min={min} max={max} value={value} onChange={(event) => onChange(clamp(Number(event.target.value)))} />
        <span className="prefs-stepper">
          <button type="button" className="prefs-stepper__btn" tabIndex={-1} aria-label={t("ui.prefs.increase", { label })} onClick={() => onChange(clamp(value + 1))}>
            <ChevronUpIcon />
          </button>
          <button type="button" className="prefs-stepper__btn" tabIndex={-1} aria-label={t("ui.prefs.decrease", { label })} onClick={() => onChange(clamp(value - 1))}>
            <ChevronDownIcon />
          </button>
        </span>
        <span className="prefs-suffix">{suffix}</span>
      </span>
    </label>
  );
}
