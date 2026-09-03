// LumaFlow v1.0 (2026-08-07)
// Barre d'en-tête de l'application : logo/titre, sélecteur de preset et menu principal
// (Photo/Presets/Préférences via HeaderMenu).

import "./HeaderBar.css";
import type { PresetEntry } from "../lib/api";
import { LogoGlyph, PresetsIcon } from "./icons";
import { HeaderMenu } from "./HeaderMenu";
import { PresetSelector } from "./PresetSelector";
import { t } from "../i18n";

type HeaderBarProps = {
  presets: PresetEntry[];
  activePresetPath: string | null;
  onSelectPreset: (path: string | null) => void;
  // onToggleSidebar removed along with the Sidebar it used to fold/unfold (2026-07-29) -- see
  // Sidebar.tsx's own header comment.
  onOpen: () => void;
  onSave: () => void;
  onExport: () => void;
  onLoadRecipe: () => void;
  onOpenBatch: () => void;
  onOpenPreferences: () => void;
};

export function HeaderBar({
  presets,
  activePresetPath,
  onSelectPreset,
  onOpen,
  onSave,
  onExport,
  onLoadRecipe,
  onOpenBatch,
  onOpenPreferences,
}: HeaderBarProps) {
  return (
    <div id="headerBar" className="header-bar">
      <div id="headerLeftZone" className="header-left-zone">
        <span className="header-logo">
          <LogoGlyph />
        </span>
        <span id="headerTitle" className="header-title">
          LumaFlow
        </span>
      </div>
      <div className="header-preset-group">
        <PresetsIcon size={16} color="var(--t1)" />
        <span className="header-preset-label">{t("ui.header.preset")}</span>
        <PresetSelector presets={presets} activePath={activePresetPath} onSelect={onSelectPreset} />
      </div>
      <div className="spacer" />
      <div className="header-actions">
        <HeaderMenu
          onOpenImage={onOpen}
          onExportImage={onExport}
          onSaveRecipe={onSave}
          onLoadRecipe={onLoadRecipe}
          onOpenBatch={onOpenBatch}
          onOpenPreferences={onOpenPreferences}
        />
      </div>
    </div>
  );
}
