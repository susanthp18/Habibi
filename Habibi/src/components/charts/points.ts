import type { PointerEvent } from "react";

/** Map pointer X to a discrete index across a series. */
export function chartIndexFromPointer(event: PointerEvent<HTMLElement>, pointCount: number) {
  if (pointCount <= 1) return 0;
  const rect = event.currentTarget.getBoundingClientRect();
  const progress = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  return Math.round(progress * (pointCount - 1));
}

export type PathPads = { top: number; bottom: number };

export const DEFAULT_PADS: PathPads = { top: 14, bottom: 16 };

/** Map a value into plot Y using an explicit domain (shared across multi-series). */
export function valueToY(
  value: number,
  height: number,
  domainMin: number,
  domainMax: number,
  pads: PathPads = DEFAULT_PADS,
) {
  const range = domainMax - domainMin || 1;
  const plotH = Math.max(1, height - pads.top - pads.bottom);
  return pads.top + (1 - (value - domainMin) / range) * plotH;
}

/**
 * Monotone cubic (Fritsch–Carlson) — smooth like the glossy sample charts,
 * but never overshoots local extrema (no dips below zero on cost series).
 */
export function buildSmoothPath(
  values: number[],
  width: number,
  height: number,
  pads: PathPads = DEFAULT_PADS,
  domainMin?: number,
  domainMax?: number,
): { line: string; area: string; min: number; max: number } {
  if (!values.length) return { line: "", area: "", min: 0, max: 1 };

  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const min = domainMin ?? Math.min(0, dataMin);
  const max = domainMax ?? Math.max(dataMax, min + 1e-6);
  const n = values.length;
  const step = n <= 1 ? 0 : width / (n - 1);
  const baseline = height - pads.bottom;

  const pts = values.map((v, i) => ({
    x: n <= 1 ? width / 2 : i * step,
    y: valueToY(v, height, min, max, pads),
  }));

  if (pts.length === 1) {
    const p = pts[0];
    return {
      line: `M0,${p.y} L${width},${p.y}`,
      area: `M0,${baseline} L0,${p.y} L${width},${p.y} L${width},${baseline} Z`,
      min,
      max,
    };
  }

  // Secant slopes
  const dx: number[] = [];
  const dy: number[] = [];
  const m: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx[i] = pts[i + 1].x - pts[i].x || 1;
    dy[i] = pts[i + 1].y - pts[i].y;
    m[i] = dy[i] / dx[i];
  }

  // Tangents
  const t: number[] = new Array(n);
  t[0] = m[0];
  t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) {
    t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
  }

  // Fritsch–Carlson restrictor — keeps the cubic monotone between knots
  for (let i = 0; i < n - 1; i++) {
    if (Math.abs(m[i]) < 1e-12) {
      t[i] = 0;
      t[i + 1] = 0;
      continue;
    }
    const a = t[i] / m[i];
    const b = t[i + 1] / m[i];
    const s = a * a + b * b;
    if (s > 9) {
      const tau = 3 / Math.sqrt(s);
      t[i] = tau * a * m[i];
      t[i + 1] = tau * b * m[i];
    }
  }

  let line = `M${pts[0].x.toFixed(2)},${pts[0].y.toFixed(2)}`;
  for (let i = 0; i < n - 1; i++) {
    const p0 = pts[i];
    const p1 = pts[i + 1];
    const cp1x = p0.x + dx[i] / 3;
    const cp1y = p0.y + (t[i] * dx[i]) / 3;
    const cp2x = p1.x - dx[i] / 3;
    const cp2y = p1.y - (t[i + 1] * dx[i]) / 3;
    line += ` C${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p1.x.toFixed(2)},${p1.y.toFixed(2)}`;
  }

  const last = pts[pts.length - 1];
  const first = pts[0];
  const area = `${line} L${last.x.toFixed(2)},${baseline.toFixed(2)} L${first.x.toFixed(2)},${baseline.toFixed(2)} Z`;
  return { line, area, min, max };
}
