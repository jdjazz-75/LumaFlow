// LumaFlow v1.0 (2026-08-07)
// Combobox de l'en-tête affichant/sélectionnant le preset (recette) actif parmi ceux du dossier
// configuré, avec repli "Nouveau" pour réinitialiser la session.

import { useEffect, useRef, useState } from "react";
import "./PresetSelector.css";
import type { PresetEntry } from "../lib/api";
import { ChevronDownIcon } from "./icons";
import { t } from "../i18n";

type PresetSelectorProps = {
  presets: PresetEntry[];
  activePath: string | null;
  onSelect: (path: string | null) => void;
};

/** Header preset combobox (2026-08-05) -- replaces the old plain-text project-name label.
Deliberately not a native <select>: its OS-rendered box can't be styled to the app's amber-accent
language and doesn't size itself to the selected text the way this trigger does (width: max-content
in the CSS, no JS measurement needed). Open/close pattern mirrors HeaderMenu.tsx's own dropdown
(root ref + outside-click/Escape dismissal). */
export function PresetSelector({ presets, activePath, onSelect }: PresetSelectorProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const activeEntry = presets.find((preset) => preset.path === activePath);
  // Falls back to the raw basename when activePath isn't among the configured directory's
  // presets (e.g. opened/exported via Presets > Ouvrir/Exporter from elsewhere) -- keeps the
  // header showing the real file name rather than silently reverting to "Nouveau".
  // A preset FILE NAME is user data, never translated -- only the "no preset" entry is.
  const label = activeEntry ? activeEntry.name : activePath ? basenameWithoutExtension(activePath) : t("ui.preset.new");

  function choose(path: string | null) {
    setOpen(false);
    onSelect(path);
  }

  return (
    <div className="preset-selector" ref={rootRef}>
      <button
        type="button"
        id="headerProjectName"
        className="preset-selector__trigger"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span className="preset-selector__label">{label}</span>
        <ChevronDownIcon />
      </button>
      {open && (
        <div className="preset-selector__panel">
          <button
            type="button"
            className={activePath === null ? "preset-selector__option preset-selector__option--active" : "preset-selector__option"}
            onClick={() => choose(null)}
          >
            {t("ui.preset.new")}
          </button>
          {presets.map((preset) => (
            <button
              type="button"
              key={preset.path}
              className={preset.path === activePath ? "preset-selector__option preset-selector__option--active" : "preset-selector__option"}
              onClick={() => choose(preset.path)}
            >
              {preset.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function basenameWithoutExtension(path: string): string {
  const base = path.split(/[/\\]/).pop() ?? path;
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(0, dot) : base;
}
