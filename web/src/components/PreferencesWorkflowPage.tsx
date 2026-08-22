// LumaFlow v1.0 (2026-08-07)
// Page "Workflow" des Préférences : activation/désactivation et réordonnancement des vignettes
// par ligne, avec import/export du fichier de configuration workflow.

import { useState } from "react";
import type { WorkflowConfigData, WorkflowVignetteConfig } from "../lib/api";
import {
  exportWorkflowConfig,
  exportWorkflowConfigDialog,
  importWorkflowConfig,
  openWorkflowConfigDialog,
} from "../lib/api";
import { describeError } from "../lib/errorMessages";
import { ChevronDownIcon, ChevronUpIcon } from "./icons";

/* Préférences > Workflow (2026-08-06): rows themselves are structurally fixed (identifier/label/
category read-only here, never authored in this UI) -- only each row's vignette enabled flag/
order is editable. Per-row vignette list is UNIFIED (every vignette the row's addon can show, each
with its own checkbox), not a curated list plus a separate "available" list, so the whole catalog
is visible with its state during administration. Reorder reuses the same hand-rolled up/down-swap
pattern this page already had (the only reorder precedent anywhere in web/src/ -- no DnD library in
the project). "neutral" stays pinned first and locked (RowSpec.__post_init__ forces it there
regardless of what's submitted, so showing it as draggable/toggleable would be misleading). Row
cards fold/unfold (2026-08-06 follow-up) -- collapsed by default, own local state, not the shared
CollapsibleSection primitive (that one assumes a borderless stacked-list look; these keep their
existing bordered card). */

type SelectedVignette = { rowIndex: number; vignetteIndex: number };

type PreferencesWorkflowPageProps = {
  config: WorkflowConfigData;
  onChange: (config: WorkflowConfigData) => void;
};

function sourceFileName(sourcePath: string): string {
  if (!sourcePath) return "";
  const segments = sourcePath.split(/[\\/]/);
  return segments[segments.length - 1] || sourcePath;
}

export function PreferencesWorkflowPage({ config, onChange }: PreferencesWorkflowPageProps) {
  const { rows } = config;
  const [selected, setSelected] = useState<SelectedVignette | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set(rows.map((row, index) => row.identifier ?? String(index))));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function onRowsChange(nextRows: typeof rows) {
    onChange({ ...config, rows: nextRows });
  }

  function updateVignettes(rowIndex: number, updater: (vignettes: WorkflowVignetteConfig[]) => WorkflowVignetteConfig[]) {
    onRowsChange(rows.map((row, index) => (index === rowIndex ? { ...row, vignettes: updater(row.vignettes) } : row)));
  }

  function toggleRowCollapsed(key: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleVignette(rowIndex: number, vignetteIndex: number) {
    if (rows[rowIndex].vignettes[vignetteIndex].identifier === "neutral") return;
    updateVignettes(rowIndex, (vignettes) =>
      vignettes.map((vignette, index) => (index === vignetteIndex ? { ...vignette, enabled: !vignette.enabled } : vignette)),
    );
  }

  function moveVignette(rowIndex: number, offset: number) {
    if (selected === null || selected.rowIndex !== rowIndex) return;
    const vignettes = rows[rowIndex].vignettes;
    const target = selected.vignetteIndex + offset;
    // Neither end of the swap may touch "neutral" (index 0, pinned) -- moving it, or moving
    // something into its slot, would silently have no visible effect (RowSpec always re-pins it).
    if (target < 1 || target >= vignettes.length || selected.vignetteIndex === 0) return;
    updateVignettes(rowIndex, (current) => {
      const next = [...current];
      [next[selected.vignetteIndex], next[target]] = [next[target], next[selected.vignetteIndex]];
      return next;
    });
    setSelected({ rowIndex, vignetteIndex: target });
  }

  async function handleOpen() {
    setError(null);
    setBusy(true);
    try {
      const { path } = await openWorkflowConfigDialog();
      if (!path) return;
      const imported = await importWorkflowConfig(path);
      onChange(imported);
      setSelected(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleExport() {
    setError(null);
    setBusy(true);
    try {
      const { path } = await exportWorkflowConfigDialog();
      if (!path) return;
      await exportWorkflowConfig(path, config);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="prefs-workflow-group">
      <div className="prefs-workflow-title">Workflow</div>
      <div className="prefs-workflow-toolbar">
        <span className="prefs-workflow-source-label">{sourceFileName(config.source_path)}</span>
        <button type="button" className="prefs-btn" onClick={handleOpen} disabled={busy}>
          Ouvrir…
        </button>
        <button type="button" className="prefs-btn" onClick={handleExport} disabled={busy}>
          Exporter…
        </button>
      </div>
      {error && <div className="prefs-error">{error}</div>}
      <div className="prefs-workflow-rows">
        {rows.map((row, rowIndex) => {
          const rowKey = row.identifier ?? String(rowIndex);
          const isOpen = !collapsed.has(rowKey);
          return (
            <div key={rowKey} className="prefs-workflow-row-card">
              <button
                type="button"
                className="prefs-workflow-row-header"
                onClick={() => toggleRowCollapsed(rowKey)}
                aria-expanded={isOpen}
              >
                {isOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}
                <span className="prefs-workflow-row-label">{row.label ?? row.identifier}</span>
              </button>
              {isOpen && (
                <>
                  <div className="prefs-workflow-vignette-list">
                    {row.vignettes.map((vignette, vignetteIndex) => {
                      const isNeutral = vignette.identifier === "neutral";
                      const isSelected = selected?.rowIndex === rowIndex && selected.vignetteIndex === vignetteIndex;
                      return (
                        <label
                          key={vignette.identifier}
                          className={
                            "prefs-workflow-vignette-item" +
                            (isSelected ? " prefs-workflow-vignette-item--selected" : "") +
                            (isNeutral ? " prefs-workflow-vignette-item--locked" : "")
                          }
                          onClick={(event) => {
                            event.preventDefault();
                            if (!isNeutral) setSelected({ rowIndex, vignetteIndex });
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={vignette.enabled}
                            disabled={isNeutral}
                            onChange={() => toggleVignette(rowIndex, vignetteIndex)}
                            onClick={(event) => event.stopPropagation()}
                          />
                          <span className="prefs-workflow-vignette-label">{vignette.label}</span>
                        </label>
                      );
                    })}
                  </div>
                  <div className="prefs-workflow-row-toolbar">
                    <button
                      type="button"
                      className="prefs-btn"
                      onClick={() => moveVignette(rowIndex, -1)}
                      disabled={selected?.rowIndex !== rowIndex || selected.vignetteIndex <= 1}
                    >
                      ▲ Monter
                    </button>
                    <button
                      type="button"
                      className="prefs-btn"
                      onClick={() => moveVignette(rowIndex, 1)}
                      disabled={
                        selected?.rowIndex !== rowIndex ||
                        selected.vignetteIndex === 0 ||
                        selected.vignetteIndex >= row.vignettes.length - 1
                      }
                    >
                      ▼ Descendre
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
