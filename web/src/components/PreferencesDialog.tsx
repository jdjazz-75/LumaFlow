// LumaFlow v1.0 (2026-08-07)
// Boîte de dialogue Préférences : charge/persiste Preferences et WorkflowConfigData, et
// orchestre ses 4 pages (Général/Workflow/Lignes/Vignettes) via une liste de catégories.

import { useEffect, useRef, useState } from "react";
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
import { getLocale, setLocale, t } from "../i18n";

/* Stable slugs, not display text (i18n phase 2, 2026-09-03) -- the visible tab name is resolved
through the catalog at render time, so switching language can never desync the active tab from the
page it selects. */
const CATEGORIES = ["general", "workflow", "lines", "vignettes"] as const;
type Category = (typeof CATEGORIES)[number];

type PreferencesDialogProps = {
  onClose: () => void;
  onSaved?: (prefs: Preferences) => void;
};

export function PreferencesDialog({ onClose, onSaved }: PreferencesDialogProps) {
  const [category, setCategory] = useState<Category>("general");
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [workflowConfig, setWorkflowConfig] = useState<WorkflowConfigData | null>(null);
  const [saving, setSaving] = useState(false);
  // La langue active à l'ouverture de la boîte, pour pouvoir la restaurer sur Annuler.
  const initialLanguage = useRef<string>(getLocale());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPreferences()
      .then((loaded) => {
        initialLanguage.current = loaded.ui_language;
        setPrefs(loaded);
      })
      .catch((err) => setError(String(err)));
    getWorkflowConfig()
      .then(setWorkflowConfig)
      .catch((err) => setError(String(err)));
  }, []);

  function updateField(key: keyof Preferences, value: number | string) {
    setPrefs((current) => (current ? { ...current, [key]: value } : current));
    // Langue (i18n phase 6): appliquée immédiatement, pour que la boîte de dialogue elle-même
    // change de langue pendant qu'on la règle -- `Annuler` la remet à la valeur persistée
    // (voir handleCancel).
    if (key === "ui_language") setLocale(value);
  }

  /* Annuler doit défaire le changement de langue en direct ci-dessus -- sans ça, fermer la boîte
  sans valider laisserait l'IHM dans la langue essayée alors que preferences.json n'a pas bougé. */
  function handleCancel() {
    setLocale(initialLanguage.current);
    onClose();
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
    <div className="prefs-overlay" onClick={handleCancel}>
      <div className="prefs-dialog" onClick={(event) => event.stopPropagation()}>
        <div className="prefs-title">{t("ui.prefs.title")}</div>
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
                {t(`ui.prefs.category.${item}`)}
              </button>
            ))}
          </div>
          <div className="prefs-page">
            {!prefs || !workflowConfig ? (
              <div className="prefs-loading">{t("ui.loading")}</div>
            ) : (
              <>
                {category === "general" && <PreferencesGeneralPage prefs={prefs} onBrowse={handleBrowse} onChange={updateField} />}
                {category === "workflow" && <PreferencesWorkflowPage config={workflowConfig} onChange={setWorkflowConfig} />}
                {category === "lines" && <PreferencesLinesPage prefs={prefs} onChange={updateField} />}
                {category === "vignettes" && <PreferencesVignettesPage prefs={prefs} onChange={updateField} />}
              </>
            )}
          </div>
        </div>
        <div className="prefs-actions">
          <button type="button" className="prefs-btn" onClick={handleCancel}>
            {t("ui.action.cancel")}
          </button>
          <button
            type="button"
            className="prefs-btn prefs-btn--primary"
            onClick={handleSave}
            disabled={!prefs || !workflowConfig || saving}
          >
            {t("ui.action.validate")}
          </button>
        </div>
      </div>
    </div>
  );
}
