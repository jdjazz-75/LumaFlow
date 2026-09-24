// LumaFlow v1.0 (2026-08-07)
// Accordéon générique réutilisable (en-tête + corps repliable) utilisé pour grouper des
// contrôles, notamment les curseurs Film/Color Splash dans le Zoom.

import { useState, type ReactNode } from "react";
import "./CollapsibleSection.css";
import { ChevronDownIcon, ChevronUpIcon } from "./icons";

type CollapsibleSectionProps = {
  title: string;
  defaultOpen?: boolean;
  /** Caller computes this (it already has the group's live values); the section only renders
  the dot -- a hint that a value inside a collapsed group differs from its default. */
  hasModifiedValue?: boolean;
  /** Controlled mode (feature 100's "Suppression d'objets" panel, ergonomics revision): when both
  are given, the section's open/closed state is driven by the caller (e.g. tied to whether an
  on-canvas correction stage is mounted) instead of its own internal state, and clicking the header
  calls `onToggle` instead of flipping local state. Omit both to keep the original uncontrolled
  behavior (every other call site) unchanged. */
  open?: boolean;
  onToggle?: () => void;
  children: ReactNode;
};

export function CollapsibleSection({ title, defaultOpen = false, hasModifiedValue = false, open: openProp, onToggle, children }: CollapsibleSectionProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const open = openProp ?? internalOpen;

  function handleClick() {
    if (onToggle) onToggle();
    else setInternalOpen((prev) => !prev);
  }

  return (
    <div className="collapsible-section">
      <button
        type="button"
        className="collapsible-section__header"
        onClick={handleClick}
        aria-expanded={open}
      >
        <span className="collapsible-section__title">{title}</span>
        {hasModifiedValue && !open && <span className="collapsible-section__dot" />}
        {open ? <ChevronUpIcon /> : <ChevronDownIcon />}
      </button>
      {open && <div className="collapsible-section__body">{children}</div>}
    </div>
  );
}
