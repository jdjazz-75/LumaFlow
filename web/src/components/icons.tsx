/* LumaFlow v1.0 (2026-08-07)
 * Bibliothèque d'icônes SVG React de l'application : glyphes d'en-tête, de guides de composition,
 * d'outils Geometry/Cadrage/Vignettage et divers boutons (Zoom, miroir, chevrons...).
 */

/* Icon set -- paths copied verbatim from the reference mockup so the glyphs
match it exactly: the mockup is the reference, not a paraphrase of it.
Reuse this file for any new icon rather than inlining SVG elsewhere. */

type IconProps = {
  size?: number;
  color?: string;
  strokeWidth?: number;
};

export function LogoGlyph({ size = 13 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="var(--amber)" strokeWidth={1.8} strokeLinecap="round">
      <path d="M12 3a9 9 0 1 0 6.5 2.8" />
    </svg>
  );
}

export function GridIcon({ size = 16, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18" />
    </svg>
  );
}

export function OpenIcon({ size = 16, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  );
}

export function SaveIcon({ size = 16, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 4h11l3 3v13H5z" />
      <path d="M8 4v5h7" />
      <path d="M8 14h8" />
    </svg>
  );
}

export function ExportIcon({ size = 16, color = "var(--amber)", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 16V4" />
      <path d="M8 8l4-4 4 4" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </svg>
  );
}

/* Header menu icons (feature: header dropdown reorganization) -- Lucide `image`/`download`/
`upload`/`file-input`/`file-output` glyphs, redrawn as <path>-only to match this file's existing
convention (icons.tsx's own header note: paths, not <line>/<polyline>/<rect> primitives, except
where an icon already used rect/circle -- ImageIcon keeps Lucide's rect+circle body since that's
the glyph's actual shape). */

export function ImageIcon({ size = 18, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="M21 15l-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
    </svg>
  );
}

export function DownloadIcon({ size = 16, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="M7 10l5 5 5-5" />
      <path d="M12 15V3" />
    </svg>
  );
}

export function UploadIcon({ size = 16, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="M17 8l-5-5-5 5" />
      <path d="M12 3v12" />
    </svg>
  );
}

export function FileInputIcon({ size = 16, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4" />
      <path d="M14 2v4a2 2 0 0 0 2 2h4" />
      <path d="M2 15h10" />
      <path d="M9 18l3-3-3-3" />
    </svg>
  );
}

export function FileOutputIcon({ size = 16, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4" />
      <path d="M14 2v4a2 2 0 0 0 2 2h4" />
      <path d="M2 15h10" />
      <path d="M5 12l-3 3 3 3" />
    </svg>
  );
}

export function HamburgerIcon({ size = 18, color = "currentColor", strokeWidth = 1.7 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

export function PresetsIcon({ size = 18, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3.5l2.6 5.3 5.9.8-4.3 4.1 1 5.8L12 16.8 6.8 19.5l1-5.8L3.5 9.6l5.9-.8z" />
    </svg>
  );
}

export function HistoryIcon({ size = 18, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 4v4h4" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}

/* Traitement par lot (2026-08-25): a stack of images, saying "many photos at once" -- the one
idea that separates this menu entry from the single-photo Ouvrir/Exporter above it. Same 24x24
viewBox/stroke conventions as every other icon in this file. */
export function BatchIcon({ size = 18, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <rect x="8" y="3.5" width="12.5" height="12.5" rx="2" />
      <path d="M11.2 8.2a1.1 1.1 0 1 0 0-.01" />
      <path d="M20.5 13.2l-3.4-3-4.6 4.1-1.8-1.6-2.7 2.4" />
      <path d="M16 19.2a1.3 1.3 0 0 1-1.3 1.3H5.2a1.7 1.7 0 0 1-1.7-1.7V8.6" />
    </svg>
  );
}

/* Lucide "settings-2" (lucide.dev, exact path data) -- replaced the "settings" gear (2026-08-05,
user feedback: the gear's many teeth rendered "tordue"/warped at this button's 16-18px size). */
export function PreferencesIcon({ size = 18, color = "currentColor", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 17H5" />
      <path d="M19 7h-9" />
      <circle cx="17" cy="17" r="3" />
      <circle cx="7" cy="7" r="3" />
    </svg>
  );
}

export function InfoIcon({ size = 13, color = "var(--t3)", strokeWidth = 1.6 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}

export function ChevronUpIcon({ size = 10, color = "currentColor", strokeWidth = 2 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 15l6-6 6 6" />
    </svg>
  );
}

export function ChevronDownIcon({ size = 10, color = "currentColor", strokeWidth = 2 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function CloseIcon({ size = 14, color = "currentColor", strokeWidth = 1.8 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

export function SplitHandleIcon({ size = 16, color = "currentColor", strokeWidth = 1.7 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 7l-4 5 4 5M15 7l4 5-4 5" />
    </svg>
  );
}

/* Composition-guide vignette glyphs (CropCanvas's guide selector) -- one minimalist icon per
framing_crop overlay kind (lib/cropGuides.ts). Always drawn on a fixed square 24x24 box regardless
of the real crop frame's aspect ratio -- these are static preview glyphs, not the live guide
itself (which cropGuides.ts computes for the frame's true proportions). */

export function ThirdsGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M9.3 2v20M14.7 2v20M2 9.3h20M2 14.7h20" />
    </svg>
  );
}

export function GoldenSectionGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M9.6 2v20M14.4 2v20M2 9.6h20M2 14.4h20" />
    </svg>
  );
}

export function GoldenTrianglesGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M2 2l20 20M22 2L13 11M2 22l9-9" />
    </svg>
  );
}

export function GoldenSpiralGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M20 4v9a9 9 0 0 1-9 9H4V13a9 9 0 0 1 9-9zM13 4v5a4 4 0 0 1-4 4H4" strokeLinecap="round" />
    </svg>
  );
}

export function CenterLinesGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M12 5v4M12 15v4M5 12h4M15 12h4" strokeLinecap="round" />
    </svg>
  );
}

export function DiagonalGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M2 2l20 20M22 2L2 22" />
    </svg>
  );
}

export function PyramidGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M12 2L2 22M12 2l10 20" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CompoundCurveGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M3 19c4-2 6 2 10 0s5-6 8-3" strokeLinecap="round" />
    </svg>
  );
}

/* Geometry addon's alignment-aid toolbar (GeometryCanvas.tsx) -- same minimalist glyph style as
the composition-guide icons above (ThirdsGuideIcon is reused directly for the 3x3 grid toggle). */

export function RotationToolIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M18 8a7 7 0 1 1-2.6-5.4" strokeLinecap="round" />
      <path d="M18 2v5h-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function DistortionToolIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M5 6h14l-2.5 12h-9z" strokeLinejoin="round" />
    </svg>
  );
}

/* Vignetting's shape-editing toolbar (VignetteShapeStage.tsx) -- "Déplacer" tool, same
minimalist glyph style/frame as RotationToolIcon/DistortionToolIcon above. */

export function MoveToolIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M12 3v18M3 12h18" strokeLinecap="round" />
      <path
        d="M12 3l-2.5 2.5M12 3l2.5 2.5M12 21l-2.5-2.5M12 21l2.5-2.5M3 12l2.5-2.5M3 12l2.5 2.5M21 12l-2.5-2.5M21 12l-2.5 2.5"
        strokeLinecap="round" strokeLinejoin="round"
      />
    </svg>
  );
}

/* Vignetting's shape-editing toolbar (VignetteShapeStage.tsx) -- "Redimensionner" tool (gates the
ellipse vertex / line border drag handles, same role as Geometry's DistortionToolIcon but depicting
an ellipse rather than a quad since Vignetting's two shapes are an ellipse and a line-band, never a
quad). */

export function ShapeToolIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <ellipse cx="12" cy="12" rx="7" ry="5" />
      <circle cx="12" cy="7" r="1.3" fill={color} stroke="none" />
      <circle cx="12" cy="17" r="1.3" fill={color} stroke="none" />
      <circle cx="19" cy="12" r="1.3" fill={color} stroke="none" />
      <circle cx="5" cy="12" r="1.3" fill={color} stroke="none" />
    </svg>
  );
}

export function VerticalLineGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M12 2v20" />
    </svg>
  );
}

export function HorizontalLineGuideIcon({ size = 16, color = "currentColor", strokeWidth = 1.4 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}>
      <rect x="2" y="2" width="20" height="20" rx="1" opacity={0.5} />
      <path d="M2 12h20" />
    </svg>
  );
}

/* Mirror toggles for the 3 orientation-sensitive guides (Golden Triangles/Spiral/Compound Curve,
see lib/cropGuides.ts's MIRROR_CAPABLE_GUIDE_KINDS) -- two independent, cumulative on/off toggles
(horizontal + vertical) rather than a single 4-way picker, so both can be active at once. */
export function MirrorHorizontalIcon({ size = 14, color = "currentColor", strokeWidth = 1.8 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2v20" strokeDasharray="2.5 2.5" />
      <path d="M5 8l-3 4 3 4M19 8l3 4-3 4" />
    </svg>
  );
}

export function MirrorVerticalIcon({ size = 14, color = "currentColor", strokeWidth = 1.8 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12h20" strokeDasharray="2.5 2.5" />
      <path d="M8 5l4-3 4 3M8 19l4 3 4-3" />
    </svg>
  );
}

/* "Agrandir" (loupe/magnifier) button on a vignette card's footer band -- path copied verbatim
from the reference mockup (its `vig.showZoomFooter` variant), the dedicated Zoom-trigger icon
FR-005 requires alongside double-click and
Espace (feature 046: this icon was speced in the mockup but never ported to VignetteCard.tsx). */
export function ZoomIcon({ size = 13, color = "currentColor", strokeWidth = 1.7 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round">
      <circle cx="11" cy="11" r="6.5" />
      <path d="M11 8.5v5M8.5 11h5M20 20l-4.5-4.5" />
    </svg>
  );
}
