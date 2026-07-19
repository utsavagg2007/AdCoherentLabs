/* Deterministic cinematic clip renderer for AdCoherent Labs.
 * Renders three 1920x1080 @ 30fps ~8s clips with node-canvas (Skia) and pipes
 * PNG frames into ffmpeg (libx264, dense keyframes for scroll scrubbing).
 *
 *   node render.js hero|signal|calm|all <outDir>
 *
 * Art direction: near-black graphite, restrained violet (#8b5cf6 family),
 * amber/red reserved for the anomaly beat, calm warm-white for clip 3.
 * Everything is seeded — same output every run. No readable text anywhere.
 */

const { createCanvas } = require("@napi-rs/canvas");
const ffmpegPath = require("ffmpeg-static");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const W = 1920, H = 1080, FPS = 30, DUR = 8, FRAMES = FPS * DUR; // 240

// ---------------------------------------------------------------- utilities

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (t) => t * t * (3 - 2 * t);
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOut = (t) => 1 - Math.pow(1 - t, 3);
// windowed progress: 0 before t0, 1 after t1, eased between
const win = (t, t0, t1, ease = smooth) => ease(clamp((t - t0) / (t1 - t0), 0, 1));
// gaussian bump centered at c with width w
const bump = (t, c, w) => Math.exp(-((t - c) * (t - c)) / (2 * w * w));

// tiny deterministic value noise (1D & 2D-ish via hashing)
function hash1(n) {
  n = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return n - Math.floor(n);
}
function noise1(x) {
  const i = Math.floor(x), f = x - i;
  return lerp(hash1(i), hash1(i + 1), smooth(f));
}
// centered noise in [-1,1]
const cnoise = (x) => noise1(x) * 2 - 1;

// ---------------------------------------------------------------- sprites

/** Cached soft radial glow sprite. tint = [r,g,b]; returns canvas. */
const spriteCache = new Map();
function glowSprite(size, r, g, b, coreWhite = 0.9) {
  const key = `${size}|${r}|${g}|${b}|${coreWhite}`;
  if (spriteCache.has(key)) return spriteCache.get(key);
  const c = createCanvas(size, size);
  const x = c.getContext("2d");
  const grad = x.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  const cr = Math.round(lerp(r, 255, coreWhite));
  const cg = Math.round(lerp(g, 255, coreWhite));
  const cb = Math.round(lerp(b, 255, coreWhite));
  grad.addColorStop(0, `rgba(${cr},${cg},${cb},1)`);
  grad.addColorStop(0.25, `rgba(${r},${g},${b},0.55)`);
  grad.addColorStop(0.6, `rgba(${r},${g},${b},0.14)`);
  grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
  x.fillStyle = grad;
  x.fillRect(0, 0, size, size);
  spriteCache.set(key, c);
  return c;
}

/** Pre-generated grain tiles (deterministic). */
const grainTiles = [];
function makeGrain(seed) {
  const rand = mulberry32(seed);
  const size = 480;
  const c = createCanvas(size, size);
  const x = c.getContext("2d");
  const img = x.createImageData(size, size);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = Math.floor(rand() * 255);
    img.data[i] = v; img.data[i + 1] = v; img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  x.putImageData(img, 0, 0);
  return c;
}
function grain(ctx, frame, alpha) {
  if (!grainTiles.length) for (let i = 0; i < 8; i++) grainTiles.push(makeGrain(9000 + i));
  const tile = grainTiles[frame % grainTiles.length];
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.globalCompositeOperation = "overlay";
  for (let y = 0; y < H; y += 480)
    for (let x = 0; x < W; x += 480) ctx.drawImage(tile, x, y);
  ctx.restore();
}

function vignette(ctx, strength, rgb = "5,6,10") {
  const g = ctx.createRadialGradient(W / 2, H / 2, H * 0.42, W / 2, H / 2, H * 0.95);
  g.addColorStop(0, `rgba(${rgb},0)`);
  g.addColorStop(1, `rgba(${rgb},${strength})`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
}

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Dense point samples along a rounded-rect perimeter (arc-length uniform). */
function roundRectPoints(x, y, w, h, r, n) {
  const pts = [];
  const seg = [];
  // param walk: edges + quarter arcs, sampled fine then resampled uniformly
  const fine = [];
  const push = (px, py) => fine.push([px, py]);
  const arc = (cx, cy, a0, a1) => {
    for (let i = 0; i <= 12; i++) {
      const a = lerp(a0, a1, i / 12);
      push(cx + r * Math.cos(a), cy + r * Math.sin(a));
    }
  };
  push(x + r, y);
  push(x + w - r, y);
  arc(x + w - r, y + r, -Math.PI / 2, 0);
  push(x + w, y + h - r);
  arc(x + w - r, y + h - r, 0, Math.PI / 2);
  push(x + r, y + h);
  arc(x + r, y + h - r, Math.PI / 2, Math.PI);
  push(x, y + r);
  arc(x + r, y + r, Math.PI, Math.PI * 1.5);
  // cumulative length
  let total = 0;
  for (let i = 1; i < fine.length; i++) {
    total += Math.hypot(fine[i][0] - fine[i - 1][0], fine[i][1] - fine[i - 1][1]);
    seg.push(total);
  }
  for (let k = 0; k < n; k++) {
    const target = (k / n) * total;
    let i = 0;
    while (i < seg.length && seg[i] < target) i++;
    const prev = i === 0 ? 0 : seg[i - 1];
    const f = seg[i] === prev ? 0 : (target - prev) / (seg[i] - prev);
    pts.push([lerp(fine[i][0], fine[i + 1][0], f), lerp(fine[i][1], fine[i + 1][1], f)]);
  }
  return pts;
}

function linePoints(x0, y0, x1, y1, n) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const t = n === 1 ? 0.5 : i / (n - 1);
    pts.push([lerp(x0, x1, t), lerp(y0, y1, t)]);
  }
  return pts;
}

/** Catmull-Rom spline through pts, arc-length resampled to `n` samples. */
function splinePoints(pts, n) {
  const fine = [];
  const P = (i) => pts[clamp(i, 0, pts.length - 1)];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = P(i - 1), p1 = P(i), p2 = P(i + 1), p3 = P(i + 2);
    for (let j = 0; j < 24; j++) {
      const t = j / 24, t2 = t * t, t3 = t2 * t;
      fine.push([
        0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
        0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
      ]);
    }
  }
  fine.push(pts[pts.length - 1].slice());
  let total = 0;
  const cum = [0];
  for (let i = 1; i < fine.length; i++) {
    total += Math.hypot(fine[i][0] - fine[i - 1][0], fine[i][1] - fine[i - 1][1]);
    cum.push(total);
  }
  const out = [];
  for (let k = 0; k < n; k++) {
    const target = (k / (n - 1)) * total;
    let i = 1;
    while (i < cum.length - 1 && cum[i] < target) i++;
    const f = (target - cum[i - 1]) / (cum[i] - cum[i - 1] || 1);
    out.push([lerp(fine[i - 1][0], fine[i][0], f), lerp(fine[i - 1][1], fine[i][1], f)]);
  }
  return out;
}

// violet family
const VIOLET = [139, 92, 246];      // #8b5cf6
const VIOLET_SOFT = [167, 139, 250]; // #a78bfa
const AMBER = [245, 158, 11];
const RED = [239, 68, 68];

// =====================================================================
// CLIP 1 — HERO ASSEMBLY: chaos -> dashboard. Monotonic for scrubbing.
// =====================================================================

function buildHeroScene() {
  const rand = mulberry32(1401);

  // ----- dashboard layout (screen space, centered) -----
  const panel = { x: 360, y: 200, w: 1200, h: 660, r: 26 };
  const cards = [
    { x: 420, y: 300, w: 320, h: 118, r: 14 },
    { x: 420, y: 448, w: 320, h: 118, r: 14 },
    { x: 420, y: 596, w: 320, h: 118, r: 14 },
  ];
  const preview = { x: 800, y: 300, w: 470, h: 414, r: 16 };
  const disclosure = { x: 836, y: 600, w: 398, h: 76, r: 10 };
  const riskArc = { cx: 1418, cy: 348, r: 52 };
  const nodes = [
    [1340, 480], [1452, 448], [1420, 560], [1330, 620], [1470, 660],
  ];
  const tracePts = [[430, 790], [700, 770], [980, 792], [1230, 772], [1480, 788]];

  // ----- particle targets, grouped with assembly windows -----
  // group: { pts, t0, t1 } — window inside [0,1] clip time
  const groups = [];
  const add = (pts, t0, t1) => groups.push({ pts, t0, t1 });

  add(roundRectPoints(panel.x, panel.y, panel.w, panel.h, panel.r, 620), 0.10, 0.40);
  cards.forEach((c, i) =>
    add(roundRectPoints(c.x, c.y, c.w, c.h, c.r, 170), 0.22 + i * 0.07, 0.50 + i * 0.07));
  // text bars inside cards
  cards.forEach((c, i) => {
    add(linePoints(c.x + 24, c.y + 38, c.x + c.w - 90, c.y + 38, 42), 0.30 + i * 0.07, 0.56 + i * 0.07);
    add(linePoints(c.x + 24, c.y + 66, c.x + c.w - 150, c.y + 66, 34), 0.32 + i * 0.07, 0.58 + i * 0.07);
  });
  add(roundRectPoints(preview.x, preview.y, preview.w, preview.h, preview.r, 300), 0.34, 0.60);
  add(roundRectPoints(disclosure.x, disclosure.y, disclosure.w, disclosure.h, disclosure.r, 130), 0.46, 0.70);
  // risk arc: three-quarter ring
  {
    const pts = [];
    for (let i = 0; i < 90; i++) {
      const a = lerp(-Math.PI * 1.25, Math.PI * 0.25, i / 89);
      pts.push([riskArc.cx + riskArc.r * Math.cos(a), riskArc.cy + riskArc.r * Math.sin(a)]);
    }
    add(pts, 0.62, 0.82);
  }
  nodes.forEach((nd, i) => {
    const pts = [];
    for (let j = 0; j < 26; j++) {
      const a = (j / 26) * Math.PI * 2;
      pts.push([nd[0] + 13 * Math.cos(a), nd[1] + 13 * Math.sin(a)]);
    }
    add(pts, 0.56 + i * 0.035, 0.76 + i * 0.035);
  });
  add(splinePoints(tracePts, 210), 0.72, 0.92);

  // ----- particles -----
  const particles = [];
  const attractors = [];
  for (let i = 0; i < 8; i++)
    attractors.push([300 + rand() * 1320, 160 + rand() * 760]);

  for (const g of groups) {
    for (const [tx, ty] of g.pts) {
      const A = attractors[Math.floor(rand() * attractors.length)];
      particles.push({
        tx, ty,
        t0: clamp(g.t0 + (rand() - 0.5) * 0.06, 0.04, 0.93),
        t1: clamp(g.t1 + (rand() - 0.5) * 0.06, 0.1, 0.97),
        ax: A[0], ay: A[1],
        orbR: 60 + rand() * 480,
        orbSpeed: (rand() * 0.5 + 0.12) * (rand() > 0.5 ? 1 : -1),
        phase: rand() * Math.PI * 2,
        wob: rand() * 100,
        z: 0.55 + rand() * 0.9,          // depth: size + alpha
        doc: rand() < 0.045,              // a few document-fragment sprites
        docW: 8 + rand() * 18,
        docH: 10 + rand() * 22,
        docA: rand() * Math.PI * 2,
      });
    }
  }
  // ambient particles that never assemble
  const ambient = [];
  for (let i = 0; i < 420; i++) {
    const A = attractors[Math.floor(rand() * attractors.length)];
    ambient.push({
      ax: A[0], ay: A[1],
      orbR: 120 + rand() * 620,
      orbSpeed: (rand() * 0.35 + 0.08) * (rand() > 0.5 ? 1 : -1),
      phase: rand() * Math.PI * 2,
      wob: rand() * 100,
      z: 0.4 + rand() * 0.8,
    });
  }
  return { panel, cards, preview, disclosure, riskArc, nodes, tracePts, particles, ambient };
}

function chaosPos(p, time) {
  const a = p.phase + p.orbSpeed * time;
  const wob = 46;
  return [
    p.ax + Math.cos(a) * p.orbR + cnoise(p.wob + time * 0.35) * wob,
    p.ay + Math.sin(a) * p.orbR * 0.62 + cnoise(p.wob + 50 + time * 0.32) * wob,
  ];
}

function renderHeroFrame(ctx, frame, S) {
  const t = frame / (FRAMES - 1);          // 0..1 clip progress
  const time = frame / FPS;                // seconds (chaos motion clock)

  // background
  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#05060a");
  bg.addColorStop(0.55, "#07080d");
  bg.addColorStop(1, "#04050a");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);
  const lift = ctx.createRadialGradient(W / 2, H * 0.46, 80, W / 2, H * 0.46, 900);
  lift.addColorStop(0, "rgba(30,28,55,0.42)");
  lift.addColorStop(1, "rgba(30,28,55,0)");
  ctx.fillStyle = lift;
  ctx.fillRect(0, 0, W, H);
  // faint drifting nebula glows
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  const neb = glowSprite(900, 96, 70, 190, 0.12);
  ctx.globalAlpha = 0.16;
  ctx.drawImage(neb, 300 + cnoise(time * 0.05) * 80, 120 + cnoise(30 + time * 0.05) * 60, 900, 900);
  ctx.globalAlpha = 0.11;
  ctx.drawImage(neb, 950 + cnoise(60 + time * 0.04) * 90, 340 + cnoise(90 + time * 0.04) * 70, 760, 760);
  ctx.restore();

  // camera push
  const scale = lerp(0.965, 1.055, easeInOut(t));
  ctx.save();
  ctx.translate(W / 2, H / 2 - 8);
  ctx.scale(scale, scale);
  ctx.translate(-W / 2, -H / 2 + 8);

  // ---- structure underlays fade in after their particles arrive ----
  const structA = win(t, 0.42, 0.78);
  if (structA > 0) {
    ctx.save();
    ctx.globalAlpha = structA * 0.5;
    ctx.strokeStyle = "rgba(139,92,246,0.35)";
    ctx.lineWidth = 1.1;
    roundRectPath(ctx, S.panel.x, S.panel.y, S.panel.w, S.panel.h, S.panel.r);
    ctx.stroke();
    ctx.globalAlpha = structA * 0.10;
    ctx.fillStyle = "#8b5cf6";
    roundRectPath(ctx, S.panel.x, S.panel.y, S.panel.w, S.panel.h, S.panel.r);
    ctx.fill();
    ctx.restore();
  }
  // card fills
  S.cards.forEach((c, i) => {
    const a = win(t, 0.52 + i * 0.06, 0.72 + i * 0.06);
    if (a <= 0) return;
    ctx.save();
    ctx.globalAlpha = a * 0.10;
    ctx.fillStyle = "#c4b5fd";
    roundRectPath(ctx, c.x, c.y, c.w, c.h, c.r);
    ctx.fill();
    ctx.restore();
  });
  // disclosure highlight: soft violet fill + slow pulse once assembled
  {
    const a = win(t, 0.66, 0.80);
    if (a > 0) {
      const pulse = 0.72 + 0.28 * Math.sin(time * 1.6);
      ctx.save();
      ctx.globalAlpha = a * (0.16 + 0.1 * pulse);
      ctx.fillStyle = "#8b5cf6";
      roundRectPath(ctx, S.disclosure.x, S.disclosure.y, S.disclosure.w, S.disclosure.h, S.disclosure.r);
      ctx.fill();
      ctx.globalAlpha = a * 0.55;
      ctx.strokeStyle = "rgba(196,181,253,0.8)";
      ctx.lineWidth = 1.2;
      roundRectPath(ctx, S.disclosure.x, S.disclosure.y, S.disclosure.w, S.disclosure.h, S.disclosure.r);
      ctx.stroke();
      ctx.restore();
    }
  }
  // citation links
  {
    const a = win(t, 0.74, 0.90);
    if (a > 0) {
      ctx.save();
      ctx.strokeStyle = "rgba(167,139,250,0.5)";
      ctx.lineWidth = 1;
      const anchors = [
        [S.cards[0].x + S.cards[0].w, S.cards[0].y + 60],
        [S.cards[1].x + S.cards[1].w, S.cards[1].y + 60],
        [S.disclosure.x + S.disclosure.w / 2, S.disclosure.y],
      ];
      S.nodes.forEach((nd, i) => {
        const from = anchors[i % anchors.length];
        const prog = win(t, 0.74 + i * 0.03, 0.88 + i * 0.03);
        if (prog <= 0) return;
        ctx.globalAlpha = a * 0.8;
        ctx.beginPath();
        ctx.moveTo(from[0], from[1]);
        const mx = lerp(from[0], nd[0], prog), my = lerp(from[1], nd[1], prog);
        const cxp = (from[0] + nd[0]) / 2 + 30, cyp = (from[1] + nd[1]) / 2 - 40;
        // partial quadratic: approximate by lerping endpoint
        ctx.quadraticCurveTo(lerp(from[0], cxp, prog), lerp(from[1], cyp, prog), mx, my);
        ctx.stroke();
      });
      ctx.restore();
    }
  }
  // risk arc value segment (amber, restrained) — completes late
  {
    const a = win(t, 0.80, 0.90);
    if (a > 0) {
      ctx.save();
      ctx.globalAlpha = a * 0.85;
      ctx.strokeStyle = "rgba(245,158,11,0.75)";
      ctx.lineWidth = 4;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.arc(S.riskArc.cx, S.riskArc.cy, S.riskArc.r - 9,
        -Math.PI * 1.25, lerp(-Math.PI * 1.25, -Math.PI * 0.75, a));
      ctx.stroke();
      ctx.restore();
    }
  }
  // verification trace completion tick + glow
  {
    const a = win(t, 0.90, 0.97);
    if (a > 0) {
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      const s = glowSprite(220, VIOLET[0], VIOLET[1], VIOLET[2], 0.6);
      ctx.globalAlpha = a * (0.5 + 0.3 * bump(t, 0.955, 0.03));
      ctx.drawImage(s, 1480 - 110, 788 - 110, 220, 220);
      ctx.restore();
      // tick
      ctx.save();
      ctx.globalAlpha = a;
      ctx.strokeStyle = "rgba(233,225,255,0.95)";
      ctx.lineWidth = 3.4;
      ctx.lineCap = "round";
      const tick = win(t, 0.915, 0.96);
      ctx.beginPath();
      ctx.moveTo(1466, 788);
      ctx.lineTo(lerp(1466, 1477, clamp(tick * 2, 0, 1)), lerp(788, 799, clamp(tick * 2, 0, 1)));
      if (tick > 0.5)
        ctx.lineTo(lerp(1477, 1498, (tick - 0.5) * 2), lerp(799, 776, (tick - 0.5) * 2));
      ctx.stroke();
      ctx.restore();
    }
  }

  // ---- particles ----
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  const sp2 = glowSprite(26, VIOLET[0], VIOLET[1], VIOLET[2], 0.75);
  const sp3 = glowSprite(40, VIOLET_SOFT[0], VIOLET_SOFT[1], VIOLET_SOFT[2], 0.85);
  for (const p of S.ambient) {
    const [x, y] = chaosPos(p, time);
    const dim = 1 - 0.4 * win(t, 0.5, 0.95);
    ctx.globalAlpha = 0.16 * p.z * dim;
    const sz = 14 * p.z;
    ctx.drawImage(sp2, x - sz / 2, y - sz / 2, sz, sz);
  }
  for (const p of S.particles) {
    const s = win(t, p.t0, p.t1, easeInOut);
    const [cx0, cy0] = chaosPos(p, time);
    // settled particles breathe very slightly
    const settleX = p.tx + cnoise(p.wob + time * 0.22) * 0.9;
    const settleY = p.ty + cnoise(p.wob + 77 + time * 0.2) * 0.9;
    const x = lerp(cx0, settleX, s);
    const y = lerp(cy0, settleY, s);
    const arrive = bump(s, 0.88, 0.1);           // flash as it locks in
    const alpha = (0.22 + 0.5 * s + 0.55 * arrive) * clamp(p.z, 0.5, 1.15);
    ctx.globalAlpha = clamp(alpha, 0, 1);
    if (p.doc && s < 0.85) {
      // document fragment: faint rotating rect that dissolves into a dot
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(p.docA + time * 0.25);
      ctx.globalAlpha = clamp(0.16 * (1 - s) * p.z, 0, 1);
      ctx.strokeStyle = "rgba(196,181,253,0.85)";
      ctx.lineWidth = 1;
      ctx.strokeRect(-p.docW / 2, -p.docH / 2, p.docW, p.docH);
      ctx.beginPath();
      ctx.moveTo(-p.docW / 2 + 2, -p.docH / 2 + 4);
      ctx.lineTo(p.docW / 2 - 3, -p.docH / 2 + 4);
      ctx.moveTo(-p.docW / 2 + 2, -p.docH / 2 + 8);
      ctx.lineTo(p.docW / 2 - 5, -p.docH / 2 + 8);
      ctx.stroke();
      ctx.restore();
    }
    const sz = (5.5 + 5.5 * p.z) * (1 + arrive * 0.9);
    ctx.drawImage(arrive > 0.25 ? sp3 : sp2, x - sz / 2, y - sz / 2, sz, sz);
  }
  ctx.restore();

  ctx.restore(); // camera

  vignette(ctx, 0.5);
  grain(ctx, frame, 0.028);
}

// =====================================================================
// CLIP 2 — SIGNAL & EVIDENCE: scan, anomaly, violet evidence trail.
// =====================================================================

function buildSignalScene() {
  const rand = mulberry32(2702);
  const layers = { far: [], mid: [], near: [] };
  const mk = (n, layer, wMin, wMax) => {
    for (let i = 0; i < n; i++) {
      const w = wMin + rand() * (wMax - wMin);
      const h = w * (0.5 + rand() * 0.45);
      layers[layer].push({
        x: -200 + rand() * 3000, y: 60 + rand() * 900, w, h,
        r: 10 + rand() * 8,
        bars: 2 + Math.floor(rand() * 4),
        hasBlock: rand() < 0.5,
        seed: rand() * 1000,
        drift: 6 + rand() * 14,
      });
    }
  };
  mk(9, "far", 140, 260);
  mk(12, "mid", 220, 430);
  mk(6, "near", 380, 560);

  // OCR boxes attach to a subset of mid cards
  const ocrTargets = [1, 3, 5, 6, 8, 10].map((i, k) => ({
    card: layers.mid[i], t0: 0.05 + k * 0.055,
  }));

  // anomaly + trail in world coords chosen so the whole story stays on screen
  // across the pan (camera ends at -430; visible world = [430, 2350]).
  const anomaly = { x: 870, y: 512, w: 280, h: 92 };
  const aC = [anomaly.x + anomaly.w / 2, anomaly.y + anomaly.h / 2];
  const anomalyHost = {
    x: anomaly.x - 34, y: anomaly.y - 96, w: anomaly.w + 70, h: anomaly.h + 150,
    r: 14, bars: 3, hasBlock: false, seed: 41.7, drift: 8,
  };

  // evidence trail: anomaly -> 3 citation nodes -> verification cluster
  const nodes = [
    [1300, 388],
    [1560, 648],
    [1790, 430],
  ];
  const cluster = [1985, 545];
  const trail = splinePoints([aC, ...nodes, cluster], 320);

  // flow lines (background data streams)
  const flows = [];
  for (let i = 0; i < 3; i++) {
    const y0 = 200 + i * 300 + rand() * 90;
    const pts = [];
    for (let k = 0; k < 6; k++)
      pts.push([-300 + k * 640, y0 + cnoise(i * 40 + k * 3) * 160]);
    flows.push({ pts: splinePoints(pts, 260), speed: 0.5 + rand() * 0.4, seed: rand() * 100 });
  }
  // claim markers on some cards
  const claims = [0, 2, 4, 7, 9, 11].map((i, k) => {
    const c = layers.mid[i];
    return { x: c.x + c.w * (0.2 + (k % 3) * 0.25), y: c.y + c.h * 0.3, t0: 0.10 + k * 0.05 };
  });
  return { layers, ocrTargets, anomaly, anomalyHost, aC, nodes, cluster, trail, flows, claims };
}

function drawCard(ctx, c, time, tone, alpha) {
  const dy = cnoise(c.seed + time * 0.18) * c.drift;
  const dx = cnoise(c.seed + 31 + time * 0.15) * c.drift * 0.6;
  ctx.save();
  ctx.translate(c.x + dx, c.y + dy);
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = tone;
  ctx.lineWidth = 1.1;
  roundRectPath(ctx, 0, 0, c.w, c.h, c.r);
  ctx.stroke();
  ctx.globalAlpha = alpha * 0.28;
  ctx.fillStyle = tone;
  roundRectPath(ctx, 0, 0, c.w, c.h, c.r);
  ctx.fill();
  // text bars
  ctx.globalAlpha = alpha * 0.85;
  ctx.lineWidth = 4;
  ctx.lineCap = "round";
  for (let b = 0; b < c.bars; b++) {
    const bw = c.w * (0.32 + hash1(c.seed + b) * 0.4);
    ctx.beginPath();
    ctx.moveTo(c.w * 0.09, c.h * 0.22 + b * (c.h * 0.16));
    ctx.lineTo(c.w * 0.09 + bw, c.h * 0.22 + b * (c.h * 0.16));
    ctx.stroke();
  }
  if (c.hasBlock) {
    ctx.globalAlpha = alpha * 0.35;
    ctx.fillRect(c.w * 0.62, c.h * 0.2, c.w * 0.28, c.h * 0.45);
  }
  ctx.restore();
  return [dx, dy];
}

function renderSignalFrame(ctx, frame, S) {
  const t = frame / (FRAMES - 1);
  const time = frame / FPS;

  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#04060c");
  bg.addColorStop(1, "#05060a");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);
  const lift = ctx.createRadialGradient(W * 0.55, H * 0.45, 60, W * 0.55, H * 0.45, 1100);
  lift.addColorStop(0, "rgba(34,32,66,0.65)");
  lift.addColorStop(1, "rgba(34,32,66,0)");
  ctx.fillStyle = lift;
  ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  const neb2 = glowSprite(900, 90, 68, 185, 0.1);
  ctx.globalAlpha = 0.14;
  ctx.drawImage(neb2, 260 + cnoise(time * 0.05) * 70, 200, 860, 860);
  ctx.globalAlpha = 0.1;
  ctx.drawImage(neb2, 1050, 90 + cnoise(40 + time * 0.04) * 60, 720, 720);
  ctx.restore();

  const camX = lerp(0, -430, easeInOut(t));
  // dim everything except anomaly during isolation beat
  const isolate = win(t, 0.30, 0.40) * (1 - win(t, 0.86, 0.96));
  const dimmed = 1 - isolate * 0.35;

  const drawLayer = (arr, par, baseA, tone) => {
    ctx.save();
    ctx.translate(camX * par, 0);
    for (const c of arr) drawCard(ctx, c, time, tone, baseA * dimmed);
    ctx.restore();
  };
  drawLayer(S.layers.far, 0.5, 0.22, "rgba(150,142,205,0.7)");

  // flow lines behind mid layer
  ctx.save();
  ctx.translate(camX * 0.75, 0);
  ctx.globalCompositeOperation = "lighter";
  const fdot = glowSprite(22, 120, 96, 235, 0.65);
  for (const f of S.flows) {
    ctx.globalAlpha = 0.16 * dimmed;
    ctx.strokeStyle = "rgba(139,92,246,0.5)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    f.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.stroke();
    for (let d = 0; d < 26; d++) {
      const u = (d / 26 + time * f.speed * 0.11 + f.seed) % 1;
      const idx = Math.floor(u * (f.pts.length - 1));
      const [x, y] = f.pts[idx];
      ctx.globalAlpha = (0.25 + 0.3 * hash1(d + f.seed)) * dimmed;
      ctx.drawImage(fdot, x - 6, y - 6, 12, 12);
    }
  }
  ctx.restore();

  drawLayer(S.layers.mid, 1.0, 0.42, "rgba(178,172,225,0.9)");

  // ---- mid-layer annotations (same parallax) ----
  ctx.save();
  ctx.translate(camX * 1.0, 0);

  // scanline sweep (early)
  const scanT = win(t, 0.03, 0.30);
  if (scanT > 0 && scanT < 1) {
    const sx = lerp(-camX * 1.0 - 100, -camX * 1.0 + W + 100, scanT);
    const g = ctx.createLinearGradient(sx - 90, 0, sx + 90, 0);
    g.addColorStop(0, "rgba(139,92,246,0)");
    g.addColorStop(0.5, "rgba(160,120,255,0.14)");
    g.addColorStop(1, "rgba(139,92,246,0)");
    ctx.fillStyle = g;
    ctx.fillRect(sx - 90, 0, 180, H);
    ctx.fillStyle = "rgba(196,181,253,0.5)";
    ctx.fillRect(sx, 0, 1.2, H);
  }

  // OCR boxes draw themselves
  for (const o of S.ocrTargets) {
    const prog = win(t, o.t0, o.t0 + 0.14);
    if (prog <= 0) continue;
    const c = o.card;
    const dy = cnoise(c.seed + time * 0.18) * c.drift;
    const dx = cnoise(c.seed + 31 + time * 0.15) * c.drift * 0.6;
    const pad = 10;
    const bx = c.x + dx - pad, by = c.y + dy - pad, bw = c.w + pad * 2, bh = c.h + pad * 2;
    ctx.save();
    ctx.globalAlpha = (0.5 + 0.5 * prog) * dimmed;
    ctx.strokeStyle = "rgba(196,181,253,0.75)";
    ctx.lineWidth = 1.3;
    const per = 2 * (bw + bh) * prog;
    ctx.setLineDash([per, 9999]);
    ctx.strokeRect(bx, by, bw, bh);
    ctx.setLineDash([]);
    if (prog > 0.9) {
      // corner ticks
      ctx.lineWidth = 2.4;
      const L = 12;
      const corners = [[bx, by, 1, 1], [bx + bw, by, -1, 1], [bx + bw, by + bh, -1, -1], [bx, by + bh, 1, -1]];
      for (const [cx0, cy0, sx0, sy0] of corners) {
        ctx.beginPath();
        ctx.moveTo(cx0 + sx0 * L, cy0);
        ctx.lineTo(cx0, cy0);
        ctx.lineTo(cx0, cy0 + sy0 * L);
        ctx.stroke();
      }
      // tag chip
      ctx.globalAlpha = 0.75 * dimmed;
      ctx.fillStyle = "rgba(139,92,246,0.85)";
      roundRectPath(ctx, bx, by - 18, 34, 12, 4);
      ctx.fill();
    }
    ctx.restore();
  }

  // claim markers
  for (const cm of S.claims) {
    const a = win(t, cm.t0, cm.t0 + 0.08);
    if (a <= 0) continue;
    const ring = win(t, cm.t0, cm.t0 + 0.2);
    ctx.save();
    ctx.translate(cm.x, cm.y);
    ctx.globalAlpha = a * dimmed;
    ctx.fillStyle = "rgba(196,181,253,0.95)";
    ctx.beginPath();
    ctx.moveTo(0, -6); ctx.lineTo(6, 0); ctx.lineTo(0, 6); ctx.lineTo(-6, 0);
    ctx.closePath();
    ctx.fill();
    if (ring < 1) {
      ctx.globalAlpha = (1 - ring) * 0.6 * dimmed;
      ctx.strokeStyle = "rgba(167,139,250,0.9)";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.arc(0, 0, 8 + ring * 26, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  // ---- anomaly beat ----
  const aAppear = win(t, 0.26, 0.34);
  if (aAppear > 0) {
    // host fragment behind the anomaly region
    drawCard(ctx, S.anomalyHost, time, "rgba(178,172,225,0.9)", 0.5);
    const resolved = win(t, 0.88, 0.95);
    const rr = Math.round(lerp(lerp(AMBER[0], RED[0], 0.45), VIOLET[0], resolved));
    const gg = Math.round(lerp(lerp(AMBER[1], RED[1], 0.45), VIOLET[1], resolved));
    const bb = Math.round(lerp(lerp(AMBER[2], RED[2], 0.45), VIOLET[2], resolved));
    const pulse = 0.75 + 0.25 * Math.sin(time * 5.2) * (1 - resolved);
    ctx.save();
    ctx.globalAlpha = aAppear * (0.85 * pulse);
    ctx.strokeStyle = `rgba(${rr},${gg},${bb},0.95)`;
    ctx.lineWidth = 2;
    roundRectPath(ctx, S.anomaly.x, S.anomaly.y, S.anomaly.w, S.anomaly.h, 6);
    ctx.stroke();
    ctx.globalAlpha = aAppear * 0.16 * pulse;
    ctx.fillStyle = `rgba(${rr},${gg},${bb},1)`;
    roundRectPath(ctx, S.anomaly.x, S.anomaly.y, S.anomaly.w, S.anomaly.h, 6);
    ctx.fill();
    // isolation iris ring
    const iris = win(t, 0.32, 0.42);
    if (iris > 0 && iris < 1) {
      ctx.globalAlpha = 0.5;
      ctx.strokeStyle = `rgba(${rr},${gg},${bb},0.8)`;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(S.aC[0], S.aC[1], lerp(430, 90, easeOut(iris)), 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
    // glow bloom
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const gs = glowSprite(300, rr, gg, bb, 0.35);
    ctx.globalAlpha = aAppear * 0.5 * pulse;
    ctx.drawImage(gs, S.aC[0] - 150, S.aC[1] - 150, 300, 300);
    ctx.restore();
  }

  // ---- evidence trail ----
  const trailT = win(t, 0.42, 0.82);
  if (trailT > 0) {
    const n = Math.max(2, Math.floor(S.trail.length * trailT));
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.lineCap = "round";
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const [x, y] = S.trail[i];
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.strokeStyle = "rgba(139,92,246,0.16)";   // wide glow ribbon
    ctx.lineWidth = 10;
    ctx.stroke();
    ctx.strokeStyle = "rgba(167,139,250,0.85)";  // bright core
    ctx.lineWidth = 3;
    ctx.stroke();
    // glowing head
    const head = S.trail[n - 1];
    const hs = glowSprite(120, VIOLET_SOFT[0], VIOLET_SOFT[1], VIOLET_SOFT[2], 0.8);
    ctx.globalAlpha = trailT < 1 ? 0.95 : 0.4;
    ctx.drawImage(hs, head[0] - 60, head[1] - 60, 120, 120);
    // particles flowing along the drawn part
    const pd = glowSprite(18, VIOLET[0], VIOLET[1], VIOLET[2], 0.85);
    for (let d = 0; d < 22; d++) {
      const u = ((d / 22 + time * 0.16) % 1) * (n / S.trail.length);
      const idx = Math.floor(u * (S.trail.length - 1));
      const [x, y] = S.trail[idx];
      ctx.globalAlpha = 0.5 + 0.4 * hash1(d * 7.3);
      ctx.drawImage(pd, x - 5, y - 5, 10, 10);
    }
    ctx.restore();
    // citation nodes light up as the head passes
    S.nodes.forEach((nd, i) => {
      const at = 0.42 + ((i + 1) / 4) * (0.82 - 0.42);
      const a = win(t, at - 0.02, at + 0.06);
      if (a <= 0) return;
      ctx.save();
      ctx.globalAlpha = a;
      ctx.strokeStyle = "rgba(196,181,253,0.9)";
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(nd[0], nd[1], 11, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "rgba(139,92,246,0.9)";
      ctx.beginPath();
      ctx.arc(nd[0], nd[1], 4, 0, Math.PI * 2);
      ctx.fill();
      // tiny citation card
      ctx.globalAlpha = a * 0.8;
      ctx.strokeStyle = "rgba(168,162,215,0.7)";
      ctx.lineWidth = 1;
      roundRectPath(ctx, nd[0] + 18, nd[1] - 26, 64, 40, 6);
      ctx.stroke();
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      for (let b = 0; b < 3; b++) {
        ctx.beginPath();
        ctx.moveTo(nd[0] + 26, nd[1] - 16 + b * 10);
        ctx.lineTo(nd[0] + 26 + 40 - b * 9, nd[1] - 16 + b * 10);
        ctx.stroke();
      }
      ctx.restore();
    });
  }

  // ---- verification cluster ----
  const clT = win(t, 0.80, 0.93);
  if (clT > 0) {
    const [cx0, cy0] = S.cluster;
    ctx.save();
    ctx.globalAlpha = clT;
    ctx.strokeStyle = "rgba(196,181,253,0.85)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx0, cy0, 44, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * clT);
    ctx.stroke();
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2 - Math.PI / 2;
      const on = clT > (i + 1) / 6;
      ctx.fillStyle = on ? "rgba(139,92,246,0.95)" : "rgba(139,92,246,0.3)";
      ctx.beginPath();
      ctx.arc(cx0 + 28 * Math.cos(a), cy0 + 28 * Math.sin(a), 4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const gs = glowSprite(260, VIOLET[0], VIOLET[1], VIOLET[2], 0.5);
    ctx.globalAlpha = clT * (0.5 + 0.3 * bump(t, 0.94, 0.03));
    ctx.drawImage(gs, cx0 - 130, cy0 - 130, 260, 260);
    ctx.restore();
  }

  ctx.restore(); // mid parallax

  drawLayer(S.layers.near, 1.45, 0.16, "rgba(125,116,185,0.7)");

  vignette(ctx, 0.55);
  grain(ctx, frame, 0.03);
}

// =====================================================================
// CLIP 3 — CALM REVIEW: bright, minimal, laptop with completed report.
// =====================================================================

function buildCalmScene() {
  const rand = mulberry32(3303);
  const motes = [];
  for (let i = 0; i < 46; i++) {
    motes.push({
      x: rand() * W, y: rand() * H * 0.8,
      vx: 6 + rand() * 10, vy: -3 - rand() * 5,
      z: 0.3 + rand() * 0.9, seed: rand() * 100,
    });
  }
  return { motes };
}

function renderCalmFrame(ctx, frame, S) {
  const t = frame / (FRAMES - 1);
  const time = frame / FPS;

  // warm daylight field
  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#f8f7f3");
  bg.addColorStop(0.62, "#f2f0ea");
  bg.addColorStop(1, "#e8e5dd");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);
  // big soft light from upper left
  const light = ctx.createRadialGradient(380, 120, 60, 380, 120, 1400);
  light.addColorStop(0, "rgba(255,254,248,0.9)");
  light.addColorStop(0.5, "rgba(255,252,244,0.25)");
  light.addColorStop(1, "rgba(255,252,244,0)");
  ctx.fillStyle = light;
  ctx.fillRect(0, 0, W, H);
  // diagonal light bands drifting very slowly
  ctx.save();
  ctx.translate(W / 2, H / 2);
  ctx.rotate(-0.32);
  for (let i = 0; i < 3; i++) {
    const off = ((time * 6 + i * 420) % 1500) - 750;
    const g = ctx.createLinearGradient(off - 130, 0, off + 130, 0);
    g.addColorStop(0, "rgba(255,255,250,0)");
    g.addColorStop(0.5, "rgba(255,255,250,0.20)");
    g.addColorStop(1, "rgba(255,255,250,0)");
    ctx.fillStyle = g;
    ctx.fillRect(off - 130, -H, 260, H * 2);
  }
  ctx.restore();

  // camera: subtle push
  const scale = lerp(1.0, 1.028, easeInOut(t));
  ctx.save();
  ctx.translate(W / 2, H / 2);
  ctx.scale(scale, scale);
  ctx.translate(-W / 2, -H / 2);

  // desk plane
  const deskY = 748;
  const desk = ctx.createLinearGradient(0, deskY, 0, H);
  desk.addColorStop(0, "#e7e2d8");
  desk.addColorStop(1, "#d8d2c6");
  ctx.fillStyle = desk;
  ctx.fillRect(0, deskY, W, H - deskY);
  ctx.fillStyle = "rgba(255,255,252,0.5)";
  ctx.fillRect(0, deskY, W, 2);

  // ---------- laptop ----------
  const lapCX = 830, screenW = 760, screenH = 470, screenY = deskY - screenH - 26;
  // soft contact shadow
  ctx.save();
  const sh = ctx.createRadialGradient(lapCX, deskY + 34, 20, lapCX, deskY + 34, 480);
  sh.addColorStop(0, "rgba(70,64,54,0.30)");
  sh.addColorStop(1, "rgba(70,64,54,0)");
  ctx.fillStyle = sh;
  ctx.save();
  ctx.translate(lapCX, deskY + 30);
  ctx.scale(1, 0.16);
  ctx.beginPath();
  ctx.arc(0, 0, 470, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  ctx.restore();

  // screen body (graphite)
  ctx.save();
  ctx.fillStyle = "#262932";
  roundRectPath(ctx, lapCX - screenW / 2, screenY, screenW, screenH, 18);
  ctx.fill();
  // display
  const dx = lapCX - screenW / 2 + 14, dy = screenY + 14, dw = screenW - 28, dh = screenH - 40;
  const disp = ctx.createLinearGradient(0, dy, 0, dy + dh);
  disp.addColorStop(0, "#fcfcfe");
  disp.addColorStop(1, "#f4f4f8");
  ctx.fillStyle = disp;
  roundRectPath(ctx, dx, dy, dw, dh, 8);
  ctx.fill();
  // screen glare
  ctx.save();
  roundRectPath(ctx, dx, dy, dw, dh, 8);
  ctx.clip();
  const glare = ctx.createLinearGradient(dx, dy, dx + dw * 0.7, dy + dh);
  glare.addColorStop(0, "rgba(255,255,255,0.5)");
  glare.addColorStop(0.35, "rgba(255,255,255,0)");
  ctx.fillStyle = glare;
  ctx.fillRect(dx, dy, dw, dh);

  // ----- calm report UI (no readable text; bars only) -----
  // header
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(dx, dy, dw, 44);
  ctx.fillStyle = "rgba(30,30,40,0.06)";
  ctx.fillRect(dx, dy + 44, dw, 1);
  ctx.fillStyle = "#8b5cf6";
  ctx.beginPath();
  ctx.arc(dx + 26, dy + 22, 7, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "rgba(40,40,55,0.5)";
  ctx.lineWidth = 4;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(dx + 46, dy + 22);
  ctx.lineTo(dx + 148, dy + 22);
  ctx.stroke();
  // status pill top-right (violet, calm)
  ctx.fillStyle = "rgba(139,92,246,0.12)";
  roundRectPath(ctx, dx + dw - 118, dy + 11, 100, 22, 11);
  ctx.fill();
  ctx.strokeStyle = "rgba(139,92,246,0.8)";
  ctx.lineWidth = 3.4;
  ctx.beginPath();
  ctx.moveTo(dx + dw - 100, dy + 22);
  ctx.lineTo(dx + dw - 40, dy + 22);
  ctx.stroke();

  // cards slide in
  const cardDefs = [
    { at: 0.10, dot: [16, 185, 129] },   // green (clear)
    { at: 0.24, dot: [245, 158, 11] },   // amber (medium)
    { at: 0.38, dot: [139, 92, 246] },   // violet (info)
  ];
  cardDefs.forEach((cd, i) => {
    const a = win(t, cd.at, cd.at + 0.14);
    if (a <= 0) return;
    const cy0 = dy + 66 + i * 96 + (1 - a) * 14;
    ctx.save();
    ctx.globalAlpha = a;
    ctx.fillStyle = "#ffffff";
    roundRectPath(ctx, dx + 22, cy0, dw - 44, 82, 10);
    ctx.fill();
    ctx.strokeStyle = "rgba(30,30,50,0.07)";
    ctx.lineWidth = 1;
    roundRectPath(ctx, dx + 22, cy0, dw - 44, 82, 10);
    ctx.stroke();
    // severity dot + bars
    ctx.fillStyle = `rgba(${cd.dot[0]},${cd.dot[1]},${cd.dot[2]},0.9)`;
    ctx.beginPath();
    ctx.arc(dx + 48, cy0 + 26, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(40,40,60,0.55)";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(dx + 68, cy0 + 26);
    ctx.lineTo(dx + 68 + 190 - i * 26, cy0 + 26);
    ctx.stroke();
    ctx.strokeStyle = "rgba(40,40,60,0.22)";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(dx + 68, cy0 + 50);
    ctx.lineTo(dx + 68 + 300 - i * 40, cy0 + 50);
    ctx.stroke();
    // chip right
    ctx.fillStyle = "rgba(139,92,246,0.10)";
    roundRectPath(ctx, dx + dw - 44 - 92, cy0 + 16, 92 - 22, 20, 10);
    ctx.fill();
    ctx.restore();
  });

  // completion check overlay
  const done = win(t, 0.58, 0.70);
  if (done > 0) {
    const pop = 0.9 + 0.1 * easeOut(done);
    ctx.save();
    ctx.globalAlpha = done;
    ctx.translate(dx + dw / 2, dy + dh / 2 + 10);
    ctx.scale(pop, pop);
    // soft glow behind
    ctx.save();
    ctx.globalCompositeOperation = "multiply";
    ctx.fillStyle = "rgba(240,238,250,0.65)";
    ctx.beginPath();
    ctx.arc(0, 0, 120, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(0, 0, 54, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(30,30,50,0.08)";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.arc(0, 0, 54, 0, Math.PI * 2);
    ctx.stroke();
    // violet ring completes
    ctx.strokeStyle = "#8b5cf6";
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(0, 0, 54, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * done);
    ctx.stroke();
    // check
    const ck = win(t, 0.64, 0.72);
    if (ck > 0) {
      ctx.strokeStyle = "#7c3aed";
      ctx.lineWidth = 7;
      ctx.beginPath();
      ctx.moveTo(-20, 2);
      ctx.lineTo(lerp(-20, -6, clamp(ck * 2, 0, 1)), lerp(2, 16, clamp(ck * 2, 0, 1)));
      if (ck > 0.5) ctx.lineTo(lerp(-6, 24, (ck - 0.5) * 2), lerp(16, -16, (ck - 0.5) * 2));
      ctx.stroke();
    }
    ctx.restore();
  }
  ctx.restore(); // display clip

  // keyboard base
  ctx.fillStyle = "#31343e";
  roundRectPath(ctx, lapCX - screenW / 2 - 40, deskY - 26, screenW + 80, 26, 8);
  ctx.fill();
  const baseHi = ctx.createLinearGradient(0, deskY - 26, 0, deskY);
  baseHi.addColorStop(0, "rgba(255,255,255,0.20)");
  baseHi.addColorStop(0.3, "rgba(255,255,255,0)");
  ctx.fillStyle = baseHi;
  roundRectPath(ctx, lapCX - screenW / 2 - 40, deskY - 26, screenW + 80, 26, 8);
  ctx.fill();
  ctx.fillStyle = "rgba(20,22,28,0.5)";
  roundRectPath(ctx, lapCX - 90, deskY - 24, 180, 8, 4);
  ctx.fill();
  ctx.restore(); // laptop group? (screen body save closed above)

  // ---------- coffee cup ----------
  const cupX = 1348, cupY = deskY + 6;
  ctx.save();
  // shadow
  ctx.save();
  ctx.translate(cupX + 14, cupY + 44);
  ctx.scale(1, 0.24);
  const csh = ctx.createRadialGradient(0, 0, 4, 0, 0, 120);
  csh.addColorStop(0, "rgba(70,64,54,0.28)");
  csh.addColorStop(1, "rgba(70,64,54,0)");
  ctx.fillStyle = csh;
  ctx.beginPath();
  ctx.arc(0, 0, 120, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  // saucer
  ctx.fillStyle = "#f4f1ea";
  ctx.save();
  ctx.translate(cupX, cupY + 40);
  ctx.scale(1, 0.24);
  ctx.beginPath();
  ctx.arc(0, 0, 92, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  // body
  const body = ctx.createLinearGradient(cupX - 60, 0, cupX + 60, 0);
  body.addColorStop(0, "#fbf9f4");
  body.addColorStop(0.55, "#ffffff");
  body.addColorStop(1, "#e9e5db");
  ctx.fillStyle = body;
  ctx.beginPath();
  ctx.moveTo(cupX - 56, cupY - 46);
  ctx.lineTo(cupX - 44, cupY + 34);
  ctx.quadraticCurveTo(cupX, cupY + 48, cupX + 44, cupY + 34);
  ctx.lineTo(cupX + 56, cupY - 46);
  ctx.closePath();
  ctx.fill();
  // handle
  ctx.strokeStyle = "#efece4";
  ctx.lineWidth = 12;
  ctx.beginPath();
  ctx.arc(cupX + 62, cupY - 8, 24, -Math.PI * 0.45, Math.PI * 0.5);
  ctx.stroke();
  // rim
  ctx.save();
  ctx.translate(cupX, cupY - 46);
  ctx.scale(1, 0.26);
  ctx.fillStyle = "#f1eee6";
  ctx.beginPath();
  ctx.arc(0, 0, 57, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#4a3428";
  ctx.beginPath();
  ctx.arc(0, 0, 48, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  ctx.restore();

  // steam wisps
  ctx.save();
  for (let wsp = 0; wsp < 3; wsp++) {
    ctx.beginPath();
    let first = true;
    for (let k = 0; k <= 30; k++) {
      const u = k / 30;
      const yy = cupY - 60 - u * 210;
      const sway = cnoise(wsp * 33 + u * 2.6 + time * 0.55) * (10 + u * 34);
      const xx = cupX - 8 + wsp * 9 + sway;
      first ? ctx.moveTo(xx, yy) : ctx.lineTo(xx, yy);
      first = false;
    }
    const sa = 0.16 * (0.6 + 0.4 * Math.sin(time * 0.8 + wsp * 2));
    ctx.strokeStyle = `rgba(120,116,110,${sa})`;
    ctx.lineWidth = 7 - wsp * 1.8;
    ctx.lineCap = "round";
    ctx.stroke();
  }
  ctx.restore();

  ctx.restore(); // camera

  // dust motes (screen space, in front)
  ctx.save();
  for (const m of S.motes) {
    const mx = (m.x + time * m.vx) % (W + 60) - 30;
    const my = (m.y + time * m.vy + H) % H;
    const tw = 0.5 + 0.5 * Math.sin(time * 0.9 + m.seed * 7);
    ctx.globalAlpha = 0.10 * m.z * tw;
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(mx, my, 1.6 * m.z + 0.6, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  // warm vignette + fine grain
  vignette(ctx, 0.16, "90,82,66");
  grain(ctx, frame, 0.02);
}

// ---------------------------------------------------------------- encoder

function encodeClip(name, outDir, renderFrame, buildScene, stills) {
  return new Promise((resolve, reject) => {
    const outPath = path.join(outDir, `${name}.mp4`);
    const ff = spawn(ffmpegPath, [
      "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "png", "-i", "pipe:0",
      "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
      "-g", "6", "-keyint_min", "6", "-sc_threshold", "0",
      "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", outPath,
    ], { stdio: ["pipe", "ignore", "pipe"] });
    let err = "";
    ff.stderr.on("data", (d) => { err += d.toString(); if (err.length > 8000) err = err.slice(-4000); });
    ff.on("error", reject);
    ff.on("close", (code) => (code === 0 ? resolve(outPath) : reject(new Error(`ffmpeg exit ${code}\n${err}`))));

    const canvas = createCanvas(W, H);
    const ctx = canvas.getContext("2d");
    const scene = buildScene();
    let frame = 0;

    const writeNext = () => {
      while (frame < FRAMES) {
        renderFrame(ctx, frame, scene);
        // stills: {frameIndex: fileName}
        if (stills && stills[frame]) {
          fs.writeFileSync(path.join(outDir, stills[frame]), canvas.toBuffer("image/jpeg", 84));
        }
        const buf = canvas.toBuffer("image/png");
        frame++;
        if (frame % 40 === 0) console.log(`  ${name}: ${frame}/${FRAMES}`);
        if (!ff.stdin.write(buf)) {
          ff.stdin.once("drain", writeNext);
          return;
        }
      }
      ff.stdin.end();
    };
    writeNext();
  });
}

async function main() {
  const which = process.argv[2] || "all";
  const outDir = process.argv[3] || path.join(process.cwd(), "out");
  fs.mkdirSync(outDir, { recursive: true });
  const jobs = {
    hero: () => encodeClip("hero-assembly", outDir, renderHeroFrame, buildHeroScene,
      { 0: "hero-poster.jpg", 234: "hero-still.jpg" }),
    signal: () => encodeClip("signal-evidence", outDir, renderSignalFrame, buildSignalScene,
      { 0: "signal-poster.jpg", 216: "signal-still.jpg" }),
    calm: () => encodeClip("calm-review", outDir, renderCalmFrame, buildCalmScene,
      { 0: "calm-poster.jpg", 220: "calm-still.jpg" }),
  };
  const list = which === "all" ? Object.keys(jobs) : [which];
  for (const j of list) {
    console.log(`rendering ${j}...`);
    const t0 = Date.now();
    const out = await jobs[j]();
    console.log(`  done ${out} in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
