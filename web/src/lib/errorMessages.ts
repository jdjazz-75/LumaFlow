// LumaFlow v1.0 (2026-08-07)
// Traduit les messages d'erreur bruts (backend/OS) en messages clairs et non techniques pour
// l'utilisateur, via un mapping unique appelé depuis chaque site setError() d'AppShell.tsx.

/** Single client-side "raw message -> clear message" mapping (feature 050, FR-004) -- applied at
every setError(...) call site in AppShell.tsx, so the same error type reads the same everywhere in
the journey, and no raw backend/OS text (a JSONDecodeError string, a Python "[Errno 2] No such
file or directory: '...'" exception message, etc.) ever reaches the user.

Two sources of `rawMessage`, handled differently:
- Recipe-load failures (feature 048) already carry a structured `category`/`details` -- preferred
  when present, since it's exact rather than inferred.
- Every other endpoint (image open, export) only ever returns a plain string -- image open/export
  are explicitly out of this feature's backend scope (FR-007: no pipeline/behavior change), so
  those raw strings are recognized by pattern rather than a server-side category field. */

export type RecipeLoadCategory = "missing_addon" | "unsupported_schema_version" | "unreadable_file" | "application_error";

function recipeLoadMessage(rawMessage: string, category: RecipeLoadCategory, details?: Record<string, unknown>): string {
  if (category === "missing_addon") {
    const ids = (details?.missing_addon_ids as string[] | undefined) ?? [];
    return ids.length > 0 ? `${rawMessage} (${ids.join(", ")})` : rawMessage;
  }
  if (category === "unsupported_schema_version") {
    const version = details?.schema_version as string | undefined;
    return version ? `${rawMessage} (version reçue : "${version}")` : rawMessage;
  }
  // unreadable_file / application_error already carry a fixed, clear message from the backend
  // -- nothing to reformulate further.
  return rawMessage;
}

// Recognizes raw Python/OS exception text for image open/export (lumaflow/engine/image_io.py),
// the one class of message an audit found leaking un-reformulated to the user --
// ordered most-specific first so a message matching several patterns picks the
// most informative one.
const RAW_MESSAGE_PATTERNS: Array<{ test: RegExp; message: string }> = [
  { test: /no space left on device|errno 28/i, message: "Espace disque insuffisant pour terminer l'opération." },
  { test: /permission denied|errno 13/i, message: "Accès refusé à ce fichier ou dossier. Vérifiez les autorisations." },
  { test: /no such file or directory|errno 2\b/i, message: "Fichier ou dossier introuvable à cet emplacement." },
  { test: /cannot identify image file/i, message: "Ce fichier image est corrompu ou illisible." },
];

// Substrings that only ever appear in raw parser/OS/stack-trace text, never in an
// already-clear message -- used to catch anything RAW_MESSAGE_PATTERNS didn't recognize by name,
// so an unrecognized-but-clearly-technical message still doesn't reach the user verbatim.
const LOOKS_TECHNICAL = /errno \d+|traceback|expecting value|jsondecodeerror|exception:/i;

/** The single mapping function every setError(...) call site in AppShell.tsx MUST go through
(FR-004). `category`/`details` come from feature 048's structured recipe-load error body when
available; omit both for every other endpoint (image open, export). */
export function toUserMessage(rawMessage: string, category?: string, details?: Record<string, unknown>): string {
  if (category) {
    return recipeLoadMessage(rawMessage, category as RecipeLoadCategory, details);
  }
  for (const { test, message } of RAW_MESSAGE_PATTERNS) {
    if (test.test(rawMessage)) return message;
  }
  if (LOOKS_TECHNICAL.test(rawMessage)) {
    return "Une erreur inattendue s'est produite. Réessayez ou choisissez un autre fichier.";
  }
  // Already a clear, product-authored message (e.g. image_io.py's own "Format d'image non pris
  // en charge (...)." for an unsupported format, or a plain ValueError like "No image loaded in
  // this session") -- passed through unchanged.
  return rawMessage;
}

/** Extracts (rawMessage, category, details) from any error thrown by web/src/lib/api.ts and
returns the final display string -- the one call every setError(...) site should make. */
export function describeError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    const apiErr = err as { message: string; category?: string; details?: Record<string, unknown> };
    return toUserMessage(apiErr.message, apiErr.category, apiErr.details);
  }
  return toUserMessage(err instanceof Error ? err.message : String(err));
}
