// LumaFlow v1.0 (2026-09-03)
// Noyau i18n : catalogues fr/en, résolution d'une clé en texte, repli sur le français puis sur la
// clé, et abonnement React pour re-rendre l'arbre au changement de langue.
/* Deliberately dependency-free (~90 lines) rather than i18next/react-intl: `package.json` carries
only react/react-dom in production, and this app needs exactly two locales, simple `{name}`
interpolation, a two-form plural (see `tn`) and no RTL. See I18N-PLAN.md, décision D2.

`t()` is a plain module function, not a hook, so it is equally callable from a component, from a
module-scope table and from a non-React helper (lib/errorMessages.ts). Components re-render on a
locale change by subscribing once via `useLocale()` -- AppShell does this at the root, which is
enough for the whole tree. */

import { useEffect, useReducer } from "react";
import enCatalog from "./en.json";
import frCatalog from "./fr.json";

export type Locale = "fr" | "en";

/** Display order of the language picker in Préférences > Général. Each `name` is deliberately
written in its OWN language (never translated) -- a reader who has landed in the wrong locale must
still recognize their own. */
export const LOCALES: { id: Locale; name: string }[] = [
  { id: "fr", name: "Français" },
  { id: "en", name: "English" },
];

/** One catalog entry. `max` is the length budget for a constrained UI zone (I18N-PLAN.md §05);
it is only present on keys rendered somewhere the layout can actually break, and is enforced by
`tests/i18n-budgets.test.mjs` over BOTH catalogs. */
export type CatalogEntry = { t: string; max?: number };
/** `_meta` (locale name, editing note) is the one key in a catalog file that is not an entry --
hence the union rather than a plain `Record<string, CatalogEntry>`; `lookup` never asks for it. */
export type Catalog = Record<string, CatalogEntry | { locale: string; name: string }>;

export const FALLBACK_LOCALE: Locale = "fr";

const CATALOGS: Record<Locale, Catalog> = {
  fr: frCatalog as Catalog,
  en: enCatalog as Catalog,
};

let current: Locale = FALLBACK_LOCALE;
const subscribers = new Set<() => void>();

export function isLocale(value: unknown): value is Locale {
  return value === "fr" || value === "en";
}

export function getLocale(): Locale {
  return current;
}

/** Switches the active locale and re-renders every subscribed component. An unknown value falls
back to French rather than throwing -- a `preferences.json` written by a future version must never
brick the UI (same tolerance as preferences.py's own validation). */
export function setLocale(locale: unknown): void {
  const next = isLocale(locale) ? locale : FALLBACK_LOCALE;
  if (next === current) return;
  current = next;
  for (const notify of subscribers) notify();
}

function interpolate(text: string, params?: Record<string, string | number>): string {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

function lookup(key: string): CatalogEntry | undefined {
  const entry = CATALOGS[current][key] ?? CATALOGS[FALLBACK_LOCALE][key];
  return entry && "t" in entry ? entry : undefined;
}

/** Resolves a catalog key. A missing key returns the key itself: visible in the UI, therefore
caught in review, rather than silently rendering an empty label. */
export function t(key: string, params?: Record<string, string | number>): string {
  const entry = lookup(key);
  return entry ? interpolate(entry.t, params) : key;
}

/** Count-aware variant: resolves `<key>.one` for exactly one item, `<key>.other` otherwise, and
passes `count` to the interpolation. Both supported locales need only that two-form distinction
(French and English agree on it), so this is deliberately not a full CLDR plural-rule engine --
adding a locale with more forms is where that becomes worth building. */
export function tn(key: string, count: number, params?: Record<string, string | number>): string {
  return t(`${key}.${count === 1 ? "one" : "other"}`, { count, ...params });
}

/** Resolves the FIRST key that exists, else `fallback` -- the shape décision D3 needs: the backend
keeps emitting its own `label`, we translate it when we recognize it, and an addon we don't know
still shows its declared label instead of a raw key. */
export function tOr(keys: string | string[], fallback: string, params?: Record<string, string | number>): string {
  for (const key of typeof keys === "string" ? [keys] : keys) {
    const entry = lookup(key);
    if (entry) return interpolate(entry.t, params);
  }
  return fallback;
}

/** True when at least one of these keys is in a catalog -- lets a caller decide between a
translated label and a backend-supplied one without resolving twice. */
export function hasKey(keys: string | string[]): boolean {
  return (typeof keys === "string" ? [keys] : keys).some((key) => lookup(key) !== undefined);
}

/** Every key declared in the reference (French) catalog, with its budget. Consumed by the
length-budget test; not used at runtime. */
export function catalogEntries(locale: Locale): [string, CatalogEntry][] {
  return Object.entries(CATALOGS[locale]).filter(
    (pair): pair is [string, CatalogEntry] => "t" in pair[1],
  );
}

/** Subscribes this component to locale changes and returns the active locale. Calling it once at
the root (AppShell) re-renders the whole tree; a component that renders outside that tree (a
portal, a future second root) needs its own call. */
export function useLocale(): Locale {
  const [, force] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    subscribers.add(force);
    return () => {
      subscribers.delete(force);
    };
  }, []);
  return current;
}
