// Pixel-art props for locations, drawn to match the 16px sprite style.
// Coordinates are world pixels; (cx, cy) is the location centre.
import { Container, Graphics } from 'pixi.js';
import type { Location } from './types';

type G = Graphics;

// Buildings sort behind anyone standing in their clearing: agents stop anywhere within a
// place's radius, including just north of the building, and must never be hidden by it.
const BEHIND = 48;

const rect = (g: G, x: number, y: number, w: number, h: number, color: number, alpha = 1) =>
  g.rect(Math.round(x), Math.round(y), w, h).fill({ color, alpha });

function shadow(g: G, cx: number, cy: number, w: number) {
  g.ellipse(cx, cy, w / 2, 3).fill({ color: 0x000000, alpha: 0.22 });
}

function workshop(cx: number, cy: number): Container {
  const c = new Container();
  const g = new Graphics();
  shadow(g, cx, cy - 3, 46);
  // chimney
  rect(g, cx + 8, cy - 42, 6, 10, 0x6d6d6d);
  rect(g, cx + 8, cy - 42, 6, 2, 0x8a8a8a);
  // walls with planks
  rect(g, cx - 18, cy - 26, 36, 22, 0x9c6b3c);
  for (let y = cy - 22; y < cy - 4; y += 4) rect(g, cx - 18, y, 36, 1, 0x7a5230);
  rect(g, cx - 18, cy - 26, 1, 22, 0x5c3a1e);
  rect(g, cx + 17, cy - 26, 1, 22, 0x5c3a1e);
  // roof
  g.poly([cx - 23, cy - 25, cx + 23, cy - 25, cx + 15, cy - 38, cx - 15, cy - 38]).fill({ color: 0x8e3b2e });
  for (let y = cy - 35; y < cy - 25; y += 3) rect(g, cx - 20 + (cy - 25 - y) * 0.5, y, 40 - (cy - 25 - y), 1, 0x6e2a20);
  rect(g, cx - 23, cy - 26, 46, 2, 0x5e2219);
  // door and window
  rect(g, cx - 4, cy - 15, 8, 11, 0x4a2e1a);
  rect(g, cx + 2, cy - 10, 1, 1, 0xd4a017);
  rect(g, cx + 8, cy - 21, 6, 5, 0x3a2a1a);
  rect(g, cx + 9, cy - 20, 4, 3, 0xf2d16b);
  rect(g, cx - 14, cy - 21, 6, 5, 0x3a2a1a);
  rect(g, cx - 13, cy - 20, 4, 3, 0xf2d16b);
  // anvil and logs
  rect(g, cx + 22, cy - 8, 9, 3, 0x5a5f66);
  rect(g, cx + 24, cy - 5, 5, 4, 0x43474d);
  rect(g, cx - 31, cy - 8, 10, 3, 0x7a5230);
  rect(g, cx - 30, cy - 11, 8, 3, 0x8b5a2b);
  c.addChild(g);
  c.zIndex = cy - BEHIND;
  return c;
}

export function drawMarket(g: G, cx: number, cy: number, stockFraction: number) {
  g.clear();
  shadow(g, cx, cy - 1, 44);
  rect(g, cx - 17, cy - 26, 2, 22, 0x6b4423);
  rect(g, cx + 15, cy - 26, 2, 22, 0x6b4423);
  // striped awning with scalloped edge
  for (let i = 0; i < 9; i++) rect(g, cx - 19 + i * 4, cy - 30, 4, 8, i % 2 ? 0xf2efe6 : 0xc0392b);
  for (let i = 0; i < 9; i++) rect(g, cx - 18 + i * 4, cy - 22, 2, 2, i % 2 ? 0xf2efe6 : 0xc0392b);
  rect(g, cx - 19, cy - 31, 36, 1, 0x7d2418);
  // counter
  rect(g, cx - 16, cy - 11, 32, 8, 0x8b5a2b);
  rect(g, cx - 16, cy - 12, 32, 2, 0xa66f3a);
  // produce: fewer items as stock runs down
  const colors = [0xe74c3c, 0xf1c40f, 0x27ae60, 0xe67e22, 0xc0392b, 0x8bc34a];
  const n = Math.round(Math.max(0, Math.min(1, stockFraction)) * 6);
  for (let i = 0; i < n; i++) rect(g, cx - 13 + i * 5, cy - 15, 3, 3, colors[i]);
  // crate
  rect(g, cx + 20, cy - 9, 9, 7, 0x9c6b3c);
  rect(g, cx + 20, cy - 9, 9, 1, 0xb98550);
  if (n > 3) {
    rect(g, cx + 21, cy - 11, 3, 2, 0xe74c3c);
    rect(g, cx + 25, cy - 11, 3, 2, 0x27ae60);
  }
}

function tent(g: G, x: number, y: number, canvas: number, shade: number) {
  shadow(g, x, y, 28);
  g.poly([x - 13, y, x + 13, y, x, y - 17]).fill({ color: canvas });
  g.poly([x, y - 17, x + 13, y, x, y]).fill({ color: shade });
  g.poly([x - 4, y, x + 4, y, x, y - 9]).fill({ color: 0x3b2a1a });
  rect(g, x - 1, y - 19, 2, 3, 0x6b4423);
}

function camp(cx: number, cy: number): Container {
  const c = new Container();
  const g = new Graphics();
  tent(g, cx - 11, cy - 1, 0xd8c08f, 0xc4a873);
  tent(g, cx + 13, cy + 7, 0x9fb7c9, 0x86a0b4);
  rect(g, cx - 4, cy + 10, 10, 4, 0x6f8f4a); // bedroll
  rect(g, cx - 4, cy + 10, 3, 4, 0xe8e2d0);
  c.addChild(g);
  c.zIndex = cy - BEHIND;
  return c;
}

function campfire(cx: number, cy: number): { container: Container; flame: Graphics; glowAt: [number, number] } {
  const c = new Container();
  const g = new Graphics();
  // benches
  rect(g, cx - 20, cy - 4, 4, 12, 0x7a5230);
  rect(g, cx - 20, cy - 4, 4, 2, 0x9c6b3c);
  rect(g, cx + 16, cy - 4, 4, 12, 0x7a5230);
  rect(g, cx + 16, cy - 4, 4, 2, 0x9c6b3c);
  rect(g, cx - 6, cy + 13, 12, 4, 0x7a5230);
  // stone ring and logs
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2;
    rect(g, cx + Math.cos(a) * 7 - 1.5, cy + Math.sin(a) * 5 - 1, 3, 3, i % 2 ? 0x8a8a8a : 0x6d6d6d);
  }
  rect(g, cx - 5, cy - 1, 10, 2, 0x5c3a1e);
  rect(g, cx - 1, cy - 4, 2, 7, 0x6b4423);
  const flame = new Graphics();
  c.addChild(g, flame);
  c.zIndex = cy;
  return { container: c, flame, glowAt: [cx, cy - 4] };
}

export function drawFlame(flame: Graphics, cx: number, cy: number, t: number) {
  const f = Math.sin(t * 0.013) * 1.2 + Math.sin(t * 0.031) * 0.8;
  flame.clear();
  flame.poly([cx - 4, cy - 1, cx + 4, cy - 1, cx + f * 0.6, cy - 11 - f]).fill({ color: 0xe67e22 });
  flame.poly([cx - 2, cy - 1, cx + 2, cy - 1, cx - f * 0.4, cy - 7 + f * 0.5]).fill({ color: 0xf9d56e });
}

export interface PropHandle {
  container: Container;
  flame?: Graphics;
  market?: Graphics;
  /** Light sources (world px) that glow at night. */
  lights: { x: number; y: number; radius: number; color: number }[];
}

export function buildProp(loc: Location, unit: number): PropHandle | null {
  const cx = loc.x * unit;
  const cy = loc.y * unit;
  switch (loc.type) {
    case 'workplace':
      return { container: workshop(cx, cy), lights: [{ x: cx - 11, y: cy - 19, radius: 16, color: 0xffc966 }, { x: cx + 11, y: cy - 19, radius: 16, color: 0xffc966 }] };
    case 'food': {
      const container = new Container();
      const g = new Graphics();
      drawMarket(g, cx, cy, loc.max_stock ? (loc.stock ?? 0) / loc.max_stock : 1);
      container.addChild(g);
      container.zIndex = cy - BEHIND;
      return { container, market: g, lights: [{ x: cx, y: cy - 24, radius: 18, color: 0xffd27a }] };
    }
    case 'rest':
      return { container: camp(cx, cy), lights: [] };
    case 'gathering': {
      const fire = campfire(cx, cy);
      return { container: fire.container, flame: fire.flame, lights: [{ x: fire.glowAt[0], y: fire.glowAt[1], radius: 44, color: 0xff9a3c }] };
    }
    default:
      return null;
  }
}
