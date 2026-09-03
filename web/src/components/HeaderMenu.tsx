// LumaFlow v1.0 (2026-08-07)
// Menu hamburger de l'en-tête : dropdown hiérarchique en accordéon (Photo/Presets) exposant
// Ouvrir/Exporter/Enregistrer et Préférences.

import { useEffect, useRef, useState } from "react";
import "./HeaderMenu.css";
import {
  BatchIcon,
  DownloadIcon,
  HamburgerIcon,
  ImageIcon,
  PreferencesIcon,
  PresetsIcon,
  UploadIcon,
} from "./icons";
import { t } from "../i18n";

type HeaderMenuProps = {
  onOpenImage: () => void;
  onExportImage: () => void;
  onSaveRecipe: () => void;
  onLoadRecipe: () => void;
  onOpenBatch: () => void;
  onOpenPreferences: () => void;
};

type ExpandedGroup = "photo" | "presets" | null;

/** Replaces the old flat Ouvrir/Enregistrer/Exporter header buttons -- a single hamburger button
(unchanged position/style) that opens a hierarchical dropdown: Photo/Presets expand in place
(accordion, same principle as CollapsibleSection in the Zoom panel -- 2026-07-29, reverted back
from a side-flyout trial) to reveal their own Ouvrir/Exporter leaf actions; Préférences is a
direct leaf. No new business logic -- every leaf just calls the same handler AppShell already
wired to the old buttons, then closes the menu. */
export function HeaderMenu({
  onOpenImage,
  onExportImage,
  onSaveRecipe,
  onLoadRecipe,
  onOpenBatch,
  onOpenPreferences,
}: HeaderMenuProps) {
  const [open, setOpen] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState<ExpandedGroup>(null);
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

  function toggleOpen() {
    setOpen((prev) => !prev);
    setExpandedGroup(null);
  }

  function toggleGroup(group: ExpandedGroup) {
    setExpandedGroup((prev) => (prev === group ? null : group));
  }

  function runLeaf(action: () => void) {
    action();
    setOpen(false);
  }

  return (
    <div className="header-menu-root" ref={rootRef}>
      <button type="button" className="header-menu" title={t("ui.header.menu")} onClick={toggleOpen} aria-expanded={open}>
        <HamburgerIcon />
      </button>
      {open && (
        <div className="header-menu-panel">
          <div className="header-menu-row-wrap">
            <button
              type="button"
              className="header-menu-item"
              onClick={() => toggleGroup("photo")}
              aria-expanded={expandedGroup === "photo"}
            >
              <ImageIcon size={16} />
              {t("ui.menu.photo")}
            </button>
            {expandedGroup === "photo" && (
              <div className="header-menu-group">
                <button type="button" className="header-menu-item header-menu-item--child" onClick={() => runLeaf(onOpenImage)}>
                  <DownloadIcon />
                  {t("ui.menu.open")}
                </button>
                <button type="button" className="header-menu-item header-menu-item--child" onClick={() => runLeaf(onExportImage)}>
                  <UploadIcon />
                  {t("ui.menu.export")}
                </button>
              </div>
            )}
          </div>

          <div className="header-menu-row-wrap">
            <button
              type="button"
              className="header-menu-item"
              onClick={() => toggleGroup("presets")}
              aria-expanded={expandedGroup === "presets"}
            >
              <PresetsIcon size={16} />
              {t("ui.menu.presets")}
            </button>
            {expandedGroup === "presets" && (
              <div className="header-menu-group">
                <button type="button" className="header-menu-item header-menu-item--child" onClick={() => runLeaf(onLoadRecipe)}>
                  <DownloadIcon />
                  {t("ui.menu.open")}
                </button>
                <button type="button" className="header-menu-item header-menu-item--child" onClick={() => runLeaf(onSaveRecipe)}>
                  <UploadIcon />
                  {t("ui.menu.export")}
                </button>
              </div>
            )}
          </div>

          {/* Direct leaf, like Préférences below it -- a batch has no sub-action to expand into,
          and it sits before Préférences because it is a working action (like Photo/Presets above)
          rather than a configuration one. */}
          <button type="button" className="header-menu-item" onClick={() => runLeaf(onOpenBatch)}>
            <BatchIcon size={16} />
            {t("ui.menu.batch")}
          </button>

          <button type="button" className="header-menu-item" onClick={() => runLeaf(onOpenPreferences)}>
            <PreferencesIcon size={16} />
            {t("ui.menu.preferences")}
          </button>
        </div>
      )}
    </div>
  );
}
