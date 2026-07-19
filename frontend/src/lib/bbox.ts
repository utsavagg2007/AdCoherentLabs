/** Tolerant bounding-box extraction from finding `location` JSON.
 * The engine's CV layer may express regions as [x0,y0,x1,y1], [x,y,w,h],
 * {x,y,w,h}, {left,top,width,height}, or a 4-point polygon — normalized or
 * pixel-space. Overlays are best-effort: no box found simply means no overlay. */

export interface FoundBox {
  x: number;
  y: number;
  w: number;
  h: number;
  normalized: boolean;
}

const BOX_KEYS = new Set([
  "bbox",
  "box",
  "bounding_box",
  "boundingbox",
  "region",
  "rect",
  "coords",
  "polygon",
  "quad",
]);

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function fromArray(arr: unknown[]): FoundBox | null {
  // 4-point polygon: [[x,y],[x,y],[x,y],[x,y]]
  if (
    arr.length === 4 &&
    arr.every(
      (p) => Array.isArray(p) && p.length >= 2 && isNum(p[0]) && isNum(p[1])
    )
  ) {
    const pts = arr as [number, number][];
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const x = Math.min(...xs);
    const y = Math.min(...ys);
    const w = Math.max(...xs) - x;
    const h = Math.max(...ys) - y;
    if (w <= 0 || h <= 0) return null;
    const normalized = Math.max(...xs, ...ys) <= 1.5;
    return { x, y, w, h, normalized };
  }
  if (arr.length === 4 && arr.every(isNum)) {
    const [a, b, c, d] = arr as number[];
    const normalized = Math.max(a, b, c, d) <= 1.5;
    // xyxy when the second pair exceeds the first; xywh otherwise
    if (c > a && d > b && (c - a) > 0 && (d - b) > 0 && (normalized || c > a + 1)) {
      return { x: a, y: b, w: c - a, h: d - b, normalized };
    }
    if (c > 0 && d > 0) return { x: a, y: b, w: c, h: d, normalized };
  }
  return null;
}

function fromObject(obj: Record<string, unknown>): FoundBox | null {
  const x = obj.x ?? obj.left;
  const y = obj.y ?? obj.top;
  const w = obj.w ?? obj.width;
  const h = obj.h ?? obj.height;
  if (isNum(x) && isNum(y) && isNum(w) && isNum(h) && w > 0 && h > 0) {
    const normalized = Math.max(x, y, w, h) <= 1.5;
    return { x, y, w, h, normalized };
  }
  const x0 = obj.x0 ?? obj.x1;
  const y0 = obj.y0 ?? obj.y1;
  const x1 = obj.x1 ?? obj.x2;
  const y1 = obj.y1 ?? obj.y2;
  if (
    isNum(x0) && isNum(y0) && isNum(x1) && isNum(y1) &&
    x1 > x0 && y1 > y0
  ) {
    const normalized = Math.max(x0, y0, x1, y1) <= 1.5;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0, normalized };
  }
  return null;
}

/** Depth-first search for the first plausible box in a location document. */
export function extractBox(value: unknown, depth = 0): FoundBox | null {
  if (value == null || depth > 6) return null;
  if (Array.isArray(value)) {
    const direct = fromArray(value);
    if (direct) return direct;
    for (const item of value) {
      const found = extractBox(item, depth + 1);
      if (found) return found;
    }
    return null;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    for (const [key, v] of Object.entries(obj)) {
      if (BOX_KEYS.has(key.toLowerCase())) {
        const found =
          Array.isArray(v)
            ? fromArray(v) ?? extractBox(v, depth + 1)
            : typeof v === "object" && v !== null
              ? fromObject(v as Record<string, unknown>) ?? extractBox(v, depth + 1)
              : null;
        if (found) return found;
      }
    }
    const direct = fromObject(obj);
    if (direct) return direct;
    for (const v of Object.values(obj)) {
      const found = extractBox(v, depth + 1);
      if (found) return found;
    }
  }
  return null;
}
