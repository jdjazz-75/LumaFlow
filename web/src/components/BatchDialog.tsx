// LumaFlow v1.0 (2026-08-25)
// Fenêtre de gestion des lots : définition des lots (fichiers/preset/répertoire de sortie),
// lancement/arrêt du traitement, jauges de progression (par lot et globale) et journal.

import { useEffect, useRef, useState } from "react";
import "./BatchDialog.css";
import * as api from "../lib/api";
import { describeError } from "../lib/errorMessages";
import { BatchIcon, CloseIcon } from "./icons";

/** One batch being defined in the window. `id` is a purely local React key -- the backend never
sees it; a batch is identified there by its POSITION in the submitted list. */
export type BatchDraft = {
  id: string;
  files: string[];
  presetPath: string | null;
  outputDir: string | null;
};

type BatchDialogProps = {
  /* Drafts and runId live in AppShell, not here: closing this window must not lose the batches
  being defined, nor detach a run that keeps going on the backend (2026-08-25 -- batches are
  session-lived, in memory only, never written to disk). */
  drafts: BatchDraft[];
  onDraftsChange: (drafts: BatchDraft[]) => void;
  runId: string | null;
  onRunIdChange: (runId: string | null) => void;
  onClose: () => void;
};

const POLL_INTERVAL_MS = 500;

export function newBatchDraft(): BatchDraft {
  return { id: `batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, files: [], presetPath: null, outputDir: null };
}

function isComplete(draft: BatchDraft): boolean {
  return draft.files.length > 0 && draft.presetPath !== null && draft.outputDir !== null;
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function BatchDialog({ drafts, onDraftsChange, runId, onRunIdChange, onClose }: BatchDialogProps) {
  const [run, setRun] = useState<api.BatchRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const running = run?.state === "running";

  /* Self-scheduling poll rather than setInterval: a render that takes longer than the interval
  would otherwise stack overlapping requests. Stops scheduling itself as soon as the run settles,
  so a finished run costs nothing while its journal stays on screen. */
  useEffect(() => {
    if (!runId) {
      setRun(null);
      return;
    }
    let cancelled = false;
    let timer: number | undefined;

    async function tick() {
      try {
        const next = await api.getBatchRun(runId as string);
        if (cancelled) return;
        setRun(next);
        if (next.state === "running") {
          timer = window.setTimeout(tick, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (!cancelled) setError(describeError(err));
      }
    }

    tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Keep the newest journal line in view while the run advances, without fighting the user if they
  // scrolled up to read an earlier failure.
  useEffect(() => {
    const element = logRef.current;
    if (!element || !running) return;
    element.scrollTop = element.scrollHeight;
  }, [run?.log.length, running]);

  function updateDraft(id: string, patch: Partial<BatchDraft>) {
    onDraftsChange(drafts.map((draft) => (draft.id === id ? { ...draft, ...patch } : draft)));
  }

  async function browse(id: string, action: () => Promise<Partial<BatchDraft> | null>) {
    setError(null);
    try {
      const patch = await action();
      if (patch) updateDraft(id, patch);
    } catch (err) {
      setError(describeError(err));
    }
  }

  async function handleRun() {
    setError(null);
    setStarting(true);
    try {
      const started = await api.startBatchRun(
        drafts.map((draft) => ({
          files: draft.files,
          preset_path: draft.presetPath as string,
          output_dir: draft.outputDir as string,
        })),
      );
      setRun(started);
      onRunIdChange(started.run_id);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setStarting(false);
    }
  }

  async function handleStop() {
    if (!runId) return;
    setError(null);
    try {
      setRun(await api.stopBatchRun(runId));
    } catch (err) {
      setError(describeError(err));
    }
  }

  /* Positional match only: batches[i] describes the i-th batch SUBMITTED. Editing the list after a
  run finished (adding/removing a batch) breaks that correspondence, so the per-block gauges step
  aside rather than attribute one batch's progress to another -- the journal, which must stay
  readable after the end, is unaffected. */
  const progressAligned = run !== null && run.batches.length === drafts.length;
  const canRun = drafts.length > 0 && drafts.every(isComplete) && !running && !starting;

  return (
    <div className="batch-overlay" onClick={onClose}>
      <div className="batch-dialog" onClick={(event) => event.stopPropagation()}>
        <div className="batch-header">
          <div className="batch-title">
            <BatchIcon size={18} />
            Traitement par lot
          </div>
          <div className="batch-global">
            <span className="batch-global__label">Progression globale</span>
            <div
              className="batch-gauge-h"
              role="progressbar"
              aria-valuenow={run?.global_percent ?? 0}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="batch-gauge-h__fill" style={{ width: `${run?.global_percent ?? 0}%` }} />
            </div>
            <span className="batch-global__percent">{run?.global_percent ?? 0} %</span>
          </div>
        </div>

        {error && <div className="batch-error">{error}</div>}

        <div className="batch-blocks">
          {drafts.length === 0 && (
            <div className="batch-empty">
              Aucun lot. Ajoutez un lot, puis choisissez ses images, son preset et son répertoire de sortie.
            </div>
          )}

          {drafts.map((draft, index) => {
            const progress = progressAligned ? run.batches[index] : undefined;
            const percent = progress?.percent ?? 0;
            return (
              <div className="batch-block" key={draft.id}>
                <div className="batch-block__body">
                  <div className="batch-block__header">
                    <span className="batch-block__name">Lot {index + 1}</span>
                    <button
                      type="button"
                      className="batch-block__remove"
                      title="Supprimer ce lot"
                      aria-label={`Supprimer le lot ${index + 1}`}
                      disabled={running}
                      onClick={() => onDraftsChange(drafts.filter((item) => item.id !== draft.id))}
                    >
                      <CloseIcon />
                    </button>
                  </div>

                  <BatchField
                    label="Fichiers"
                    value={
                      draft.files.length > 0
                        ? `${draft.files.length} fichier${draft.files.length > 1 ? "s" : ""} sélectionné${draft.files.length > 1 ? "s" : ""}`
                        : null
                    }
                    title={draft.files.join("\n")}
                    disabled={running}
                    onBrowse={() =>
                      browse(draft.id, async () => {
                        const files = await api.selectBatchFilesDialog();
                        return files.length > 0 ? { files } : null;
                      })
                    }
                  />
                  <BatchField
                    label="Preset"
                    value={draft.presetPath ? baseName(draft.presetPath) : null}
                    title={draft.presetPath ?? ""}
                    disabled={running}
                    onBrowse={() =>
                      browse(draft.id, async () => {
                        const { path } = await api.loadRecipeDialog();
                        return path ? { presetPath: path } : null;
                      })
                    }
                  />
                  <BatchField
                    label="Sortie"
                    value={draft.outputDir}
                    title={draft.outputDir ?? ""}
                    disabled={running}
                    onBrowse={() =>
                      browse(draft.id, async () => {
                        const { path } = await api.selectBatchOutputDirectoryDialog();
                        return path ? { outputDir: path } : null;
                      })
                    }
                  />
                </div>

                <div
                  className="batch-gauge-v"
                  role="progressbar"
                  aria-valuenow={percent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="batch-gauge-v__fill" style={{ height: `${percent}%` }} />
                </div>
                <span className="batch-block__percent">{percent} %</span>
              </div>
            );
          })}

          <button
            type="button"
            className="batch-add"
            disabled={running}
            onClick={() => onDraftsChange([...drafts, newBatchDraft()])}
          >
            + Ajouter un lot
          </button>
        </div>

        <div className="batch-log-section">
          <div className="batch-log-header">
            <span className="batch-log-title">Journal</span>
            {run && <span className="batch-log-summary">{summarize(run)}</span>}
          </div>
          <div className="batch-log" ref={logRef}>
            {!run || run.log.length === 0 ? (
              <div className="batch-log__idle">Le journal se remplira pendant l'exécution.</div>
            ) : (
              run.log.map((entry) => (
                <div
                  key={entry.index}
                  className={`batch-log__line ${entry.ok ? "batch-log__line--ok" : "batch-log__line--error"}`}
                >
                  <span className="batch-log__mark">{entry.ok ? "✔" : "✖"}</span>
                  <span className="batch-log__counter">
                    {entry.index}/{entry.total}
                  </span>
                  <span className="batch-log__file" title={entry.file_name}>
                    {entry.file_name}
                  </span>
                  <span className="batch-log__detail">
                    {entry.ok ? `→ ${entry.output_name}` : entry.message}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="batch-actions">
          <button type="button" className="batch-btn" onClick={onClose}>
            Fermer
          </button>
          {running ? (
            <button type="button" className="batch-btn batch-btn--primary" onClick={handleStop}>
              Arrêter
            </button>
          ) : (
            <button type="button" className="batch-btn batch-btn--primary" onClick={handleRun} disabled={!canRun}>
              Exécuter
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function summarize(run: api.BatchRun): string {
  const counts = `${run.success_count} réussite${run.success_count > 1 ? "s" : ""}, ${run.error_count} échec${run.error_count > 1 ? "s" : ""}`;
  if (run.state === "running") return `${run.done}/${run.total} — ${counts}`;
  if (run.state === "stopped") return `Arrêté à ${run.done}/${run.total} — ${counts}`;
  return `Terminé — ${counts}`;
}

type BatchFieldProps = {
  label: string;
  value: string | null;
  title: string;
  disabled: boolean;
  onBrowse: () => void;
};

function BatchField({ label, value, title, disabled, onBrowse }: BatchFieldProps) {
  return (
    <div className="batch-field">
      <span className="batch-field__label">{label}</span>
      <span
        className={value ? "batch-field__value" : "batch-field__value batch-field__value--empty"}
        title={title}
      >
        {value ?? "Non renseigné"}
      </span>
      <button type="button" className="batch-browse-btn" disabled={disabled} onClick={onBrowse}>
        Parcourir…
      </button>
    </div>
  );
}
