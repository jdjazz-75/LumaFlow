// LumaFlow v1.0 (2026-08-07)
// Boîte de dialogue Préférences : charge/persiste Preferences et WorkflowConfigData, et
// orchestre ses 4 pages (Général/Workflow/Lignes/Vignettes) via une liste de catégories.

import { useEffect, useState } from "react";
import "./PreferencesDialog.css";
import {
  getPreferences,
  getWorkflowConfig,
  putPreferences,
  putWorkflowConfig,
  type Preferences,
  type WorkflowConfigData,
} from "../lib/api";
import { PreferencesGeneralPage, type PathField } from "./PreferencesGeneralPage";
import { PreferencesLinesPage } from "./PreferencesLinesPage";
import { PreferencesVignettesPage } from "./PreferencesVignettesPage";
import { PreferencesWorkflowPage } from "./PreferencesWorkflowPage";

const CATEGORIES = ["Général", "Workflow", "Lignes", "Vignettes"] as const;
type Category = (typeof CATEGORIES)[number];

type PreferencesDialogProps = {
  onClose: () => void;
  onSaved?: (prefs: Preferences) => void;
};

export function PreferencesDialog({ onClose, onSaved }: PreferencesDialogProps) {
  const [category, setCategory] = useState<Category>("Général");
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [workflowConfig, setWorkflowConfig] = useState<WorkflowConfigData | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPreferences()
      .then(setPrefs)
      .catch((err) => setError(String(err)));
    getWorkflowConfig()
      .then(setWorkflowConfig)
      .catch((err) => setError(String(err)));
  }, []);

  function updateField(key: keyof Preferences, value: number | string) {
    setPrefs((current) => (current ? { ...current, [key]: value } : current));
  }

  async function handleBrowse(field: PathField, dialog: () => Promise<{ path: string | null }>) {
    const { path } = await dialog();
    if (path) setPrefs((current) => (current ? { ...current, [field]: path } : current));
  }

  async function handleSave() {
    if (!prefs || !workflowConfig) return;
    setSaving(true);
    setError(null);
    try {
      // Mirrors the current Workflow tab's source_path into prefs so PUT /preferences persists it
      // (survives an app restart) -- PUT /workflow-config only updates the in-process copy, for
      // immediate reflection within this run, to avoid both endpoints racing to write the same
      // preferences.json.
      const prefsWithWorkflowSource = { ...prefs, workflow_config_source_path: workflowConfig.source_path };
      const [saved] = await Promise.all([putPreferences(prefsWithWorkflowSource), putWorkflowConfig(workflowConfig)]);
      onSaved?.(saved);
      onClose();
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="prefs-overlay" onClick={onClose}>
      <div className="prefs-dialog" onClick={(event) => event.stopPropagation()}>
        <div className="prefs-title">Préférences</div>
        {error && <div className="prefs-error">{error}</div>}
        <div className="prefs-body">
          <div className="prefs-category-list">
            {CATEGORIES.map((item) => (
              <button
                key={item}
                type="button"
                className={item === category ? "prefs-category-item prefs-category-item--active" : "prefs-category-item"}
                onClick={() => setCategory(item)}
              >
                {item}
              </button>
            ))}
          </div>
          <div className="prefs-page">
            {!prefs || !workflowConfig ? (
              <div className="prefs-loading">Chargement…</div>
            ) : (
              <>
                {category === "Général" && <PreferencesGeneralPage prefs={prefs} onBrowse={handleBrowse} onChange={updateField} />}
                {category === "Workflow" && <PreferencesWorkflowPage config={workflowConfig} onChange={setWorkflowConfig} />}
                {category === "Lignes" && <PreferencesLinesPage prefs={prefs} onChange={updateField} />}
                {category === "Vignettes" && <PreferencesVignettesPage prefs={prefs} onChange={updateField} />}
              </>
            )}
          </div>
        </div>
        <div className="prefs-actions">
          <button type="button" className="prefs-btn" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="prefs-btn prefs-btn--primary"
            onClick={handleSave}
            disabled={!prefs || !workflowConfig || saving}
          >
            Valider
          </button>
        </div>
      </div>
    </div>
  );
}
