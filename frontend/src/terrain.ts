// Deterministic terrain for a world: grass patches, dirt clearings and paths, forests.
// Purely visual; the simulation itself has no terrain.
import type { Location, WorldView } from './types';

/** Screen pixels per world unit (one 16px tile = 2 world units). */
export const UNIT = 8;
export const TILE_UNITS = 2;

export const GRASS1 = 0;
export const GRASS2 = 1;
export const DIRT = 2;

export interface Terrain {
  cols: number;
  rows: number;
  tiles: Uint8Array;
  /** Tree positions in world units (base of the trunk). */
  trees: { x: number; y: number }[];
}

function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Smooth value noise in [0, 1] on a lattice with the given cell size (in tiles). */
function valueNoise(seed: number, cell: number) {
  const lattice = (ix: number, iy: number) => mulberry32(seed ^ Math.imul(ix, 374761393) ^ Math.imul(iy, 668265263))();
  const smooth = (t: number) => t * t * (3 - 2 * t);
  return (x: number, y: number) => {
    const gx = x / cell;
    const gy = y / cell;
    const ix = Math.floor(gx);
    const iy = Math.floor(gy);
    const fx = smooth(gx - ix);
    const fy = smooth(gy - iy);
    const a = lattice(ix, iy);
    const b = lattice(ix + 1, iy);
    const c = lattice(ix, iy + 1);
    const d = lattice(ix + 1, iy + 1);
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  };
}

/** Minimum spanning tree over locations (Prim), so every place is reachable by path. */
function spanningEdges(locs: Location[]): [Location, Location][] {
  if (locs.length < 2) return [];
  const inTree = new Set([locs[0].id]);
  const edges: [Location, Location][] = [];
  while (inTree.size < locs.length) {
    let best: [Location, Location] | null = null;
    let bestD = Infinity;
    for (const a of locs) {
      if (!inTree.has(a.id)) continue;
      for (const b of locs) {
        if (inTree.has(b.id)) continue;
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d < bestD) {
          bestD = d;
          best = [a, b];
        }
      }
    }
    if (!best) break;
    edges.push(best);
    inTree.add(best[1].id);
  }
  return edges;
}

export function generateTerrain(world: Pick<WorldView, 'id' | 'width' | 'height' | 'locations'>): Terrain {
  const cols = Math.ceil(world.width / TILE_UNITS);
  const rows = Math.ceil(world.height / TILE_UNITS);
  const seed = hashString(world.id);
  const rng = mulberry32(seed);
  const patches = valueNoise(seed ^ 0x9e3779b9, 6);
  const forest = valueNoise(seed ^ 0x85ebca6b, 9);
  const tiles = new Uint8Array(cols * rows);
  const idx = (c: number, r: number) => r * cols + c;
  const inside = (c: number, r: number) => c >= 0 && r >= 0 && c < cols && r < rows;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      tiles[idx(c, r)] = patches(c, r) > 0.58 || rng() < 0.06 ? GRASS2 : GRASS1;
    }
  }

  // Dirt clearings under every location, with a ragged edge.
  for (const loc of world.locations) {
    const radius = loc.radius * 0.95;
    const c0 = Math.floor((loc.x - radius - 2) / TILE_UNITS);
    const r0 = Math.floor((loc.y - radius - 2) / TILE_UNITS);
    const c1 = Math.ceil((loc.x + radius + 2) / TILE_UNITS);
    const r1 = Math.ceil((loc.y + radius + 2) / TILE_UNITS);
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        if (!inside(c, r)) continue;
        const d = Math.hypot((c + 0.5) * TILE_UNITS - loc.x, (r + 0.5) * TILE_UNITS - loc.y);
        if (d < radius - 1 || (d < radius + 1 && rng() < 0.55)) tiles[idx(c, r)] = DIRT;
      }
    }
  }

  // Gently winding paths between locations.
  const pathTiles = new Set<number>();
  for (const [a, b] of spanningEdges(world.locations)) {
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    const steps = Math.ceil(len / (TILE_UNITS * 0.4));
    const nx = -(b.y - a.y) / (len || 1);
    const ny = (b.x - a.x) / (len || 1);
    const phase = rng() * Math.PI * 2;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const wiggle = Math.sin(t * Math.PI * 2 + phase) * Math.sin(t * Math.PI) * Math.min(4, len * 0.06);
      const x = a.x + (b.x - a.x) * t + nx * wiggle;
      const y = a.y + (b.y - a.y) * t + ny * wiggle;
      const c = Math.floor(x / TILE_UNITS);
      const r = Math.floor(y / TILE_UNITS);
      if (inside(c, r)) {
        tiles[idx(c, r)] = DIRT;
        pathTiles.add(idx(c, r));
      }
    }
  }

  // Forests: thicker towards the edges and in noise clusters, never on paths or near locations.
  const trees: { x: number; y: number }[] = [];
  const edgeBand = Math.max(4, Math.min(cols, rows) * 0.16);
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (tiles[idx(c, r)] === DIRT) continue;
      let nearPath = false;
      for (let dr = -1; dr <= 1 && !nearPath; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          if (pathTiles.has(idx(c + dc, r + dr))) {
            nearPath = true;
            break;
          }
        }
      }
      if (nearPath) continue;
      const x = (c + 0.5) * TILE_UNITS;
      const y = (r + 0.5) * TILE_UNITS;
      if (world.locations.some((l) => Math.hypot(l.x - x, l.y - y) < l.radius + 4)) continue;
      const edgeDist = Math.min(c, r, cols - 1 - c, rows - 1 - r);
      const edge = Math.max(0, 1 - edgeDist / edgeBand);
      let density = 0.025 + 0.55 * edge * edge;
      if (forest(c, r) > 0.64) density += 0.3;
      if (rng() < density) trees.push({ x: x + (rng() - 0.5) * 0.8, y: y + (rng() - 0.5) * 0.8 });
    }
  }
  return { cols, rows, tiles, trees };
}

/** Darkness of the night overlay (0 = full day) for a tick. */
export function nightAlpha(tick: number, ticksPerDay: number): number {
  const hour = ((tick % ticksPerDay) * 24) / ticksPerDay;
  if (hour >= 7 && hour <= 18) return 0;
  if (hour > 18 && hour < 21) return ((hour - 18) / 3) * 0.5;
  if (hour > 5 && hour < 7) return ((7 - hour) / 2) * 0.5;
  return 0.5;
}
