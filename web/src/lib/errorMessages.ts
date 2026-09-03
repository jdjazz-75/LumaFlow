// LumaFlow v1.0 (2026-09-03)
// Traduit les erreurs brutes (backend structuré/OS) en messages clairs et localisés, via le
// catalogue i18n, appelé depuis chaque site setError() d'AppShell.tsx.
/** Single client-side "raw error -> clear, localized message" mapping (feature 050, FR-004;
généralisé en i18n phase 4, 2026-09-03) -- applied at every setError(...) call site in
AppShell.tsx/BatchDialog.tsx/PreferencesWorkflowPage.tsx, so the same error type reads the same
everywhere in the journey, and no raw backend/OS text (a JSONDecodeError string, a Python
"[Errno 2] No such file or directory: '...'" exception message, etc.) ever reaches the user.

Two sources of a raw error, handled by tier:
1. A STRUCTURED body -- `category` (+ `code`/`details`) from api.ts's StructuredErrorDetail. Every
   endpoint that raises a category the frontend recognizes (see CATEGORY_KEYS below) resolves
   through the i18n catalog -- décision D3's repli pattern applied to errors: the backend's own
   `message` (French, fixed) is the fallback for a category this build's catalog does not know,
   never the primary source once a translation exists.
2. A plain STRING -- every endpoint not yet migrated to a structured body only ever returns raw
   text (image open/export's OWN message is now structured, but a handful of invariant-violation
   strings like "No image loaded in this session" still aren't -- see RAW_MESSAGE_PATTERNS'
   comment). Recognized by pattern rather than a category field. */

import { t, tOr } from "../i18n";

export type RecipeLoadCategory = "missing_addon" | "unsupported_schema_version" | "unreadable_file" | "application_error";

/** category -> catalog key, for every structured error body the backend can raise. Two recipe-load
categories are handled separately (recipeLoadMessage below) because they interpolate `details`
into the sentence rather than using a flat translation. `invalid_batch` is ALSO handled separately
(batchValidationMessage) since its real cause lives in `code`, not `category`. */
const CATEGORY_KEYS: Record<string, string> = {
  unreadable_file: "error.recipe.unreadable_file",
  application_error: "error.recipe.application_error",
  destination_exists: "error.destination_exists",
  batch_already_running: "error.batch.already_running",
  // lumaflow/engine/errors.py's ErrorCategory (image open/export)
  missing_file: "error.file_not_found",
  permission_denied: "error.permission_denied",
  unsupported_format: "error.unsupported_format",
  corrupted_file: "error.unreadable_image",
  raw_not_decodable: "error.raw_not_decodable",
  invalid_path: "error.file_not_found",
  disk_full: "error.no_space_left",
  unknown: "error.unexpected",
};

/** batch_runs.py's BatchValidationError.code -> catalog key. */
const BATCH_VALIDATION_KEYS: Record<string, string> = {
  no_batches: "error.batch.no_batches",
  empty_batch: "error.batch.empty_batch",
  preset_not_found: "error.batch.preset_not_found",
  output_dir_not_found: "error.batch.output_dir_not_found",
};

function recipeLoadMessage(rawMessage: string, category: RecipeLoadCategory, details?: Record<string, unknown>): string {
  if (category === "missing_addon") {
    const ids = (details?.missing_addon_ids as string[] | undefined) ?? [];
    const message = tOr("error.recipe.missing_addon", rawMessage);
    return ids.length > 0 ? t("error.recipe.missing_addon_detail", { message, ids: ids.join(", ") }) : message;
  }
  if (category === "unsupported_schema_version") {
    const version = details?.schema_version as string | undefined;
    const message = tOr("error.recipe.unsupported_schema_version", rawMessage);
    return version ? t("error.recipe.unsupported_schema_version_detail", { message, version }) : message;
  }
  return tOr(`error.recipe.${category}`, rawMessage);
}

function batchValidationMessage(rawMessage: string, code: string | undefined): string {
  const key = code ? BATCH_VALIDATION_KEYS[code] : undefined;
  return key ? t(key) : rawMessage;
}

// Recognizes raw Python/OS exception text NOT already carried as a structured `category` (a
// handful of endpoints -- e.g. "No image loaded in this session" -- still raise a plain string;
// see this module's header comment) -- ordered most-specific first so a message matching several
// patterns picks the most informative one.
const RAW_MESSAGE_PATTERNS: Array<{ test: RegExp; key: string }> = [
  { test: /no space left on device|errno 28/i, key: "error.no_space_left" },
  { test: /permission denied|errno 13/i, key: "error.permission_denied" },
  { test: /no such file or directory|errno 2\b/i, key: "error.file_not_found" },
  { test: /cannot identify image file/i, key: "error.unreadable_image" },
];

// Substrings that only ever appear in raw parser/OS/stack-trace text, never in an
// already-clear message -- used to catch anything RAW_MESSAGE_PATTERNS didn't recognize by name,
// so an unrecognized-but-clearly-technical message still doesn't reach the user verbatim.
const LOOKS_TECHNICAL = /errno \d+|traceback|expecting value|jsondecodeerror|exception:/i;

/** The single mapping function every setError(...) call site MUST go through (FR-004). `category`/
`code`/`details` come from api.ts's ApiError when the raising endpoint sends a structured body;
omit them for the handful of endpoints that still raise a plain string. */
export function toUserMessage(
  rawMessage: string,
  category?: string,
  details?: Record<string, unknown>,
  code?: string,
): string {
  if (category === "missing_addon" || category === "unsupported_schema_version") {
    return recipeLoadMessage(rawMessage, category, details);
  }
  if (category === "invalid_batch") {
    return batchValidationMessage(rawMessage, code);
  }
  if (category) {
    const key = CATEGORY_KEYS[category];
    if (key) return t(key);
    // An unrecognized category (a third-party addon's own endpoint, or a future backend category
    // this build's catalog predates) -- the backend's own message is still a clear, product-
    // authored sentence, so it is shown as-is rather than falling through to the technical-text
    // heuristics below (those exist for plain strings, which carry no such guarantee).
    return rawMessage;
  }
  for (const { test, key } of RAW_MESSAGE_PATTERNS) {
    if (test.test(rawMessage)) return t(key);
  }
  if (LOOKS_TECHNICAL.test(rawMessage)) {
    return t("error.unexpected");
  }
  // Already a clear, product-authored message (e.g. a plain ValueError like "No image loaded in
  // this session") -- passed through unchanged; not yet migrated to a structured category, and not
  // technical-looking enough to warrant the generic fallback above.
  return rawMessage;
}

/** Extracts (rawMessage, category, details, code) from any error thrown by web/src/lib/api.ts and
returns the final display string -- the one call every setError(...) site should make. */
export function describeError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    const apiErr = err as { message: string; category?: string; details?: Record<string, unknown>; code?: string };
    return toUserMessage(apiErr.message, apiErr.category, apiErr.details, apiErr.code);
  }
  return toUserMessage(err instanceof Error ? err.message : String(err));
}
