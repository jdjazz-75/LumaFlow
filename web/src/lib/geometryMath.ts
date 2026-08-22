// LumaFlow v1.0 (2026-08-07)
// Résolution d'une transformation perspective (homographie) à partir de 4 correspondances de
// points, pour faire suivre les guides d'alignement de Geometry au quadrilatère déformé.

// Pure client-side homography math for the Geometry addon's ephemeral alignment guides (movable
// vertical/horizontal line, movable 3x3 grid) -- lets those guides visually follow the dragged
// corner quad instead of staying axis-aligned while the frame is deformed. Purely a visual aid:
// this never needs to be bit-identical to the backend's own solve
// (lumaflow/addons/builtin/geometry.py's _solve_perspective_coefficients), only visually
// consistent with it -- the backend's numpy solve is the only implementation that actually
// determines the rendered pixels.
//
// Both sides solve the same 8x8 linear system for 4 point correspondences under PIL's perspective
// convention -- for a point (x,y): x' = (a*x + b*y + c) / (g*x + h*y + 1), y' = (d*x + e*y + f) /
// (g*x + h*y + 1). Because the fractional [0,1]x[0,1] coordinate space used throughout the web UI
// is just a per-axis rescaling of the backend's real pixel space, and a projective transform
// conjugated by a diagonal (non-uniform axis) scaling is still a projective transform, solving
// directly in fractional space (rather than converting to real pixels first) yields the
// on-screen-correct result once drawn into the same viewBox="0 0 1 1" SVG that GeometryCanvas (and
// CropCanvas before it) stretches non-uniformly onto the rendered photo.

export type Point = { x: number; y: number };
export type PerspectiveCoefficients = readonly [number, number, number, number, number, number, number, number];

/** Solves the 8 coefficients of a perspective transform such that, for each i,
applyPerspective(coeffs, fromPoints[i]) ~= toPoints[i]. Exactly 4 correspondences are required (8
unknowns, an exact solve -- not a least-squares fit). Returns null for a (near-)degenerate/singular
system (e.g. collinear points) instead of throwing, so callers can fall back to leaving a guide
unprojected rather than crashing mid-drag. */
export function solvePerspectiveCoefficients(fromPoints: Point[], toPoints: Point[]): PerspectiveCoefficients | null {
  if (fromPoints.length !== 4 || toPoints.length !== 4) {
    throw new Error("solvePerspectiveCoefficients requires exactly 4 point correspondences");
  }
  const matrix: number[][] = [];
  const vector: number[] = [];
  for (let i = 0; i < 4; i += 1) {
    const { x: fx, y: fy } = fromPoints[i];
    const { x: tx, y: ty } = toPoints[i];
    matrix.push([fx, fy, 1, 0, 0, 0, -fx * tx, -fy * tx]);
    vector.push(tx);
    matrix.push([0, 0, 0, fx, fy, 1, -fx * ty, -fy * ty]);
    vector.push(ty);
  }
  const solved = solveLinearSystem(matrix, vector);
  if (!solved) return null;
  return solved as unknown as PerspectiveCoefficients;
}

/** Projects a single point through a solved perspective transform. */
export function applyPerspective(coeffs: PerspectiveCoefficients, point: Point): Point {
  const [a, b, c, d, e, f, g, h] = coeffs;
  const denom = g * point.x + h * point.y + 1;
  return { x: (a * point.x + b * point.y + c) / denom, y: (d * point.x + e * point.y + f) / denom };
}

/** Gaussian elimination with partial pivoting for a square linear system `matrix * x = vector`.
Returns null (instead of throwing) when the matrix is singular/near-singular -- the standard "3+
collinear corners" degenerate case for this module's callers. A small fixed 8x8 system here, not
worth pulling in a linear-algebra dependency for. */
function solveLinearSystem(matrix: number[][], vector: number[]): number[] | null {
  const n = vector.length;
  const augmented = matrix.map((row, i) => [...row, vector[i]]);

  for (let col = 0; col < n; col += 1) {
    let pivotRow = col;
    let pivotValue = Math.abs(augmented[col][col]);
    for (let row = col + 1; row < n; row += 1) {
      if (Math.abs(augmented[row][col]) > pivotValue) {
        pivotRow = row;
        pivotValue = Math.abs(augmented[row][col]);
      }
    }
    if (pivotValue < 1e-9) return null;
    if (pivotRow !== col) [augmented[col], augmented[pivotRow]] = [augmented[pivotRow], augmented[col]];

    for (let row = col + 1; row < n; row += 1) {
      const factor = augmented[row][col] / augmented[col][col];
      for (let k = col; k <= n; k += 1) augmented[row][k] -= factor * augmented[col][k];
    }
  }

  const solution = new Array<number>(n).fill(0);
  for (let row = n - 1; row >= 0; row -= 1) {
    let sum = augmented[row][n];
    for (let k = row + 1; k < n; k += 1) sum -= augmented[row][k] * solution[k];
    solution[row] = sum / augmented[row][row];
  }
  return solution;
}
