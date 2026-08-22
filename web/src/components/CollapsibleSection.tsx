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
  children: ReactNode;
};

export function CollapsibleSection({ title, defaultOpen = false, hasModifiedValue = false, children }: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="collapsible-section">
      <button
        type="button"
        className="collapsible-section__header"
        onClick={() => setOpen((prev) => !prev)}
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
