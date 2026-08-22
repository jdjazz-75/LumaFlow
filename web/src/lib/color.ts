// LumaFlow v1.0 (2026-08-07)
// Conversions de couleur (hex <-> HSL <-> RGB), plus contraste de texte pour la couleur
// d'accentuation configurable -- utilisé par ColorWheel.tsx et AppShell.tsx.

// Hex <-> HSL conversions for ColorWheel.tsx's hex text field (feature 2026-07-27). No
// hex-color parsing/formatting utility existed anywhere in web/src/lib/ prior to this.

const HEX_PATTERN = /^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/;

export function hslToHex(hue: number, saturationPct: number, lightnessPct: number): string {
  const h = ((hue % 360) + 360) % 360;
  const s = Math.max(0, Math.min(100, saturationPct)) / 100;
  const l = Math.max(0, Math.min(100, lightnessPct)) / 100;

  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;

  let rp = 0;
  let gp = 0;
  let bp = 0;
  if (h < 60) [rp, gp, bp] = [c, x, 0];
  else if (h < 120) [rp, gp, bp] = [x, c, 0];
  else if (h < 180) [rp, gp, bp] = [0, c, x];
  else if (h < 240) [rp, gp, bp] = [0, x, c];
  else if (h < 300) [rp, gp, bp] = [x, 0, c];
  else [rp, gp, bp] = [c, 0, x];

  const toHexByte = (value: number) =>
    Math.round((value + m) * 255)
      .toString(16)
      .padStart(2, "0")
      .toUpperCase();

  return `#${toHexByte(rp)}${toHexByte(gp)}${toHexByte(bp)}`;
}

export function hexToHsl(hex: string): { hue: number; saturation: number; lightness: number } | null {
  const match = HEX_PATTERN.exec(hex.trim());
  if (!match) return null;

  const digits = match[1];
  const expanded = digits.length === 3 ? digits.split("").map((c) => c + c).join("") : digits;
  const r = parseInt(expanded.slice(0, 2), 16) / 255;
  const g = parseInt(expanded.slice(2, 4), 16) / 255;
  const b = parseInt(expanded.slice(4, 6), 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;

  if (max === min) return { hue: 0, saturation: 0, lightness: l * 100 };

  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  switch (max) {
    case r:
      h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
      break;
    case g:
      h = ((b - r) / d + 2) * 60;
      break;
    default:
      h = ((r - g) / d + 4) * 60;
  }

  return { hue: h, saturation: s * 100, lightness: l * 100 };
}

// Couleur d'accentuation personnalisable (Préférences > Général, 2026-08-07) -- appliquée au
// runtime via des CSS custom properties (AppShell.tsx), ces deux helpers dérivent ce dont
// tokens.css a besoin en plus du hex brut : le triplet RGB pour composer des rgba() côté CSS
// (une custom property hex ne peut pas être décomposée en CSS pur), et une couleur de texte
// contrastée pour les fonds pleins accent (boutons d'action, pastille de statut active...).
function hexToRgbBytes(hex: string): { r: number; g: number; b: number } | null {
  const match = HEX_PATTERN.exec(hex.trim());
  if (!match) return null;
  const digits = match[1];
  const expanded = digits.length === 3 ? digits.split("").map((c) => c + c).join("") : digits;
  return {
    r: parseInt(expanded.slice(0, 2), 16),
    g: parseInt(expanded.slice(2, 4), 16),
    b: parseInt(expanded.slice(4, 6), 16),
  };
}

export function hexToRgbTriplet(hex: string): string {
  const rgb = hexToRgbBytes(hex);
  if (!rgb) return "227, 167, 94";
  return `${rgb.r}, ${rgb.g}, ${rgb.b}`;
}

export function contrastTextColor(hex: string): string {
  const rgb = hexToRgbBytes(hex);
  if (!rgb) return "#05080a";
  const luminance = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
  return luminance > 0.55 ? "#05080a" : "#ffffff";
}
