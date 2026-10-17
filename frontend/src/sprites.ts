// Sprite sheets ("Puny Characters" pack): metadata, animations and texture loading.
//
// Character sheets are 768x256: 24 columns x 8 rows of 32x32 frames.
//   rows    = facing direction, clockwise from south: S, SE, E, NE, N, NW, W, SW
//   columns = 0 stand · 1-4 walk · 5-8 swing · 9-12 bow · 13-15 raise/throw · 20 hit flash · 23 lying down
import { Assets, Rectangle, Texture } from 'pixi.js';

export const FRAME = 32;
export const TILE = 16;
export const SHEET_COLS = 24;

export type Anim = 'stand' | 'walk' | 'work' | 'swing' | 'raise' | 'hurt' | 'lie';

export const ANIMS: Record<Anim, { frames: number[]; fps: number }> = {
  stand: { frames: [0], fps: 1 },
  walk: { frames: [1, 2, 3, 4], fps: 8 },
  work: { frames: [5, 6, 8, 6], fps: 5 }, // tool swing without the slash arc
  swing: { frames: [5, 6, 7, 8], fps: 10 }, // sword swing (theft / conflict)
  raise: { frames: [13, 14], fps: 3 }, // arm raised (creating, studying)
  hurt: { frames: [20], fps: 1 },
  lie: { frames: [23], fps: 1 },
};

export const CHARACTER_SHEETS = [
  'archer-green', 'archer-purple', 'human-soldier-cyan', 'human-soldier-red', 'human-worker-cyan', 'human-worker-red',
  'mage-cyan', 'mage-red', 'orc-grunt', 'orc-peon-cyan', 'orc-peon-red', 'orc-soldier-cyan', 'orc-soldier-red',
  'soldier-blue', 'soldier-red', 'soldier-yellow', 'warrior-blue', 'warrior-red',
] as const;

export const ENVIRONMENT = ['dirt', 'grass1', 'grass2', 'tree'] as const;

export const sheetUrl = (sheet: string) => `/sprites/characters/${sheet}.png`;
export const tileUrl = (tile: string) => `/sprites/environment/${tile}.png`;

export const ARCHETYPE_LABELS: Record<string, string> = {
  mage: 'Mage — spiritual, scientific or artistic',
  archer: 'Archer — curious or risk-taking',
  warrior: 'Warrior — ambitious or competitive',
  soldier: 'Soldier — persistent',
  'human-worker': 'Villager — sociable, agreeable, generous or empathetic',
  'human-soldier': 'Guard — honest or impulsive',
  orc: 'Orc — strongest trait is criminal tendency',
};

export function archetypeOf(sheet: string | undefined): string {
  if (!sheet) return 'human-worker';
  if (sheet.startsWith('orc')) return 'orc';
  return sheet.replace(/-(red|cyan|blue|green|purple|yellow)$/, '');
}

/** Facing row from a movement vector in screen space (y grows downwards). */
export function directionRow(dx: number, dy: number, previous = 0): number {
  if (Math.abs(dx) < 1e-6 && Math.abs(dy) < 1e-6) return previous;
  const octant = (Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) + 8) % 8; // 0=E,1=SE,2=S,...
  return (2 - octant + 8) % 8;
}

/** Which animation an agent plays for its current activity. */
export function animFor(action: string, alive: boolean, moving: boolean): Anim {
  if (!alive) return 'lie';
  if (moving) return 'walk';
  switch (action) {
    case 'work':
      return 'work';
    case 'steal':
      return 'swing';
    case 'create':
    case 'study':
      return 'raise';
    case 'rest':
      return 'lie';
    default:
      return 'stand';
  }
}

export const ACTION_EMOTES: Record<string, string> = {
  work: '⚒', eat: '🍞', buy_food: '🛒', rest: '💤', socialize: '💬', talk: '✉️', explore: '🧭', reflect: '💭',
  create: '🎨', study: '📖', give: '🎁', offer_trade: '🤝', accept_trade: '🤝', reject_trade: '✋', steal: '🗡️',
  move: '', idle: '', dead: '🪦',
};

// ---------------------------------------------------------------- textures
const frameCache = new Map<string, Texture>();

export async function loadSpriteTextures(): Promise<void> {
  const urls = [...CHARACTER_SHEETS.map(sheetUrl), ...ENVIRONMENT.map(tileUrl)];
  const textures = await Assets.load<Texture>(urls);
  for (const url of urls) {
    // Pixel art must never be smoothed when scaled.
    textures[url].source.scaleMode = 'nearest';
  }
}

export function tileTexture(tile: (typeof ENVIRONMENT)[number]): Texture {
  return Assets.get<Texture>(tileUrl(tile));
}

export function frameTexture(sheet: string, col: number, row: number): Texture {
  const known = (CHARACTER_SHEETS as readonly string[]).includes(sheet) ? sheet : 'human-worker-red';
  const key = `${known}:${col}:${row}`;
  let tex = frameCache.get(key);
  if (!tex) {
    const base = Assets.get<Texture>(sheetUrl(known));
    tex = new Texture({ source: base.source, frame: new Rectangle(col * FRAME, row * FRAME, FRAME, FRAME) });
    frameCache.set(key, tex);
  }
  return tex;
}
