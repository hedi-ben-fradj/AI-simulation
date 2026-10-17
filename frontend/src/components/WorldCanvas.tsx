import { useEffect, useRef, useState } from 'react';
import { ActionIcon, Group, Text as MText, Tooltip } from '@mantine/core';
import {
  Application, Container, FederatedPointerEvent, Graphics, RenderTexture, Sprite, Text, TextStyle, Texture,
} from 'pixi.js';
import type { AgentBrief, WorldView } from '../types';
import { MOOD_COLORS } from '../theme';
import {
  ACTION_EMOTES, ANIMS, FRAME, TILE, animFor, directionRow, frameTexture, loadSpriteTextures, tileTexture,
} from '../sprites';
import { DIRT, GRASS2, UNIT, generateTerrain, nightAlpha } from '../terrain';
import { buildProp, drawFlame, drawMarket, type PropHandle } from '../props';

export type ThoughtMode = 'off' | 'selected' | 'all';

interface Props {
  world: WorldView | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Expected time between ticks; movement is interpolated over (most of) it. */
  tickIntervalMs: number;
  thoughts: ThoughtMode;
  /** Agents of the conversation in focus: highlighted and followed; everyone else is dimmed. */
  focus?: string[] | null;
  onClearFocus?: () => void;
}

const FONT = '"Pixelify Sans", system-ui, sans-serif';
const SPEECH_MS = 4500;
const THOUGHT_MS = 3000;
const MAX_THOUGHTS = 3;
const CROWDED_AGENTS = 40;
const HURT_MS = 350;
const ENVELOPE_MS = 1100;
const DIMMED_ALPHA = 0.3;
// Feet sit at y = 23 of the 32px frame.
const ANCHOR_Y = 23 / FRAME;
// The initial view zooms in at most this far (screen px per sprite px).
const DEFAULT_MAX_SCALE = 2.5;

/** Agents standing at the same spot are fanned out around it (visual only). */
function crowdOffset(id: string, index: number, count: number): { dx: number; dy: number } {
  if (count <= 1) return { dx: 0, dy: 0 };
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  // A shallow arc in front of (below) the spot, so nobody hides behind a building.
  const spread = Math.PI * 1.3;
  const angle = -Math.PI * 0.15 + (index / (count - 1)) * spread + ((h % 5) - 2) * 0.03;
  const r = 9 + count * 1.5;
  return { dx: -Math.cos(angle) * r, dy: 3 + Math.sin(angle) * r * 0.6 };
}

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

/** A letter flying from sender to recipient when a message is sent. */
interface Envelope {
  g: Graphics;
  from: string;
  to: string;
  start: number;
}

function makeEnvelope(): Graphics {
  const g = new Graphics();
  g.rect(-4, -3, 8, 6).fill({ color: 0xfff8e7 }).stroke({ width: 1, color: 0x5c3a1e });
  g.moveTo(-4, -3).lineTo(0, 0.5).lineTo(4, -3).stroke({ width: 1, color: 0x5c3a1e });
  return g;
}

interface AgentNode {
  data: AgentBrief;
  body: Container; // world-space: shadow, halo, selection, sprite
  sprite: Sprite;
  ring: Graphics;
  focusRing: Graphics;
  halo: Graphics;
  label: Container; // screen-space
  name: Text;
  dot: Graphics;
  bar: Graphics;
  emote: Text;
  from: { x: number; y: number };
  to: { x: number; y: number };
  pos: { x: number; y: number };
  start: number;
  duration: number;
  row: number;
  hurtUntil: number;
  speech: Container | null;
  speechUntil: number;
  thought: Container | null;
  thoughtUntil: number;
  lastSaid: string | null;
  lastIntention: string | null;
  lastHealth: number;
}

function makeBubble(text: string, kind: 'speech' | 'thought'): Container {
  const c = new Container();
  const t = new Text({
    text: text.length > 140 ? `${text.slice(0, 137)}…` : text,
    style: new TextStyle({
      fontFamily: FONT, fontSize: 12, fill: kind === 'speech' ? 0x2b2118 : 0xf3ecff,
      wordWrap: true, wordWrapWidth: 170, lineHeight: 14,
    }),
  });
  const pad = 6;
  const w = Math.ceil(t.width) + pad * 2;
  const h = Math.ceil(t.height) + pad * 2;
  const g = new Graphics();
  if (kind === 'speech') {
    // Parchment speech box with a pixel border.
    g.rect(0, 0, w, h).fill({ color: 0xf6ecd2 }).stroke({ width: 2, color: 0x5c3a1e });
    g.poly([w / 2 - 5, h, w / 2 + 5, h, w / 2, h + 6]).fill({ color: 0x5c3a1e });
  } else {
    g.roundRect(0, 0, w, h, 8).fill({ color: 0x241b3a, alpha: 0.9 }).stroke({ width: 1, color: 0xb197fc, alpha: 0.9 });
    g.circle(w / 2, h + 5, 3).fill({ color: 0x241b3a, alpha: 0.9 });
  }
  t.position.set(pad, pad);
  c.addChild(g, t);
  c.pivot.set(w / 2, h + 8);
  (c as any).__size = { w, h: h + 8 };
  return c;
}

class Scene {
  app: Application;
  host: HTMLElement;
  root = new Container(); // camera
  ground = new Sprite();
  objects = new Container();
  darkness = new Graphics();
  lights = new Container();
  fx = new Container(); // world space, above everything: message envelopes
  envelopes: Envelope[] = [];
  focus: Set<string> | null = null;
  focusKey = '';
  followGroup = false;
  overlay = new Container(); // screen space
  locLabels = new Container();
  agentLabels = new Container();
  bubbles = new Container();
  agents = new Map<string, AgentNode>();
  props: { handle: PropHandle; loc: WorldView['locations'][number] }[] = [];
  lightSprites: { g: Graphics; radius: number }[] = [];
  world: WorldView | null = null;
  terrainKey = '';
  mapW = 0;
  mapH = 0;
  fit = 1; // scale at which the whole map is visible
  cover = 1; // scale at which the map fills the view
  zoom = 1; // relative to fit
  center = { x: 0, y: 0 }; // world px at screen centre
  selectedId: string | null = null;
  thoughts: ThoughtMode = 'all';
  follow = false;
  onSelect: (id: string | null) => void;
  drag: { x: number; y: number; cx: number; cy: number; moved: boolean } | null = null;
  removeWheel: () => void;

  constructor(app: Application, host: HTMLElement, onSelect: (id: string | null) => void) {
    this.app = app;
    this.host = host;
    this.onSelect = onSelect;
    this.objects.sortableChildren = true;
    this.lights.blendMode = 'add';
    this.root.addChild(this.ground, this.objects, this.darkness, this.lights, this.fx);
    this.overlay.addChild(this.locLabels, this.agentLabels, this.bubbles);
    app.stage.addChild(this.root, this.overlay);
    app.stage.eventMode = 'static';
    app.stage.hitArea = app.screen;
    app.stage.on('pointerdown', (e: FederatedPointerEvent) => {
      this.drag = { x: e.global.x, y: e.global.y, cx: this.center.x, cy: this.center.y, moved: false };
    });
    app.stage.on('globalpointermove', (e: FederatedPointerEvent) => {
      if (!this.drag) return;
      const dx = e.global.x - this.drag.x;
      const dy = e.global.y - this.drag.y;
      if (!this.drag.moved && Math.hypot(dx, dy) < 4) return;
      this.drag.moved = true;
      this.follow = false;
      this.followGroup = false;
      const s = this.scale();
      this.center = { x: this.drag.cx - dx / s, y: this.drag.cy - dy / s };
      this.clampCenter();
    });
    const end = (e: FederatedPointerEvent) => {
      if (this.drag && !this.drag.moved && e.target === app.stage) this.onSelect(null);
      this.drag = null;
    };
    app.stage.on('pointerup', end);
    app.stage.on('pointerupoutside', end);
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = (app.canvas as HTMLCanvasElement).getBoundingClientRect();
      this.zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - rect.left, e.clientY - rect.top);
    };
    app.canvas.addEventListener('wheel', wheel, { passive: false });
    this.removeWheel = () => app.canvas.removeEventListener('wheel', wheel);
    app.renderer.on('resize', () => this.layout());
    app.ticker.add(() => this.frame());
  }

  scale() {
    return this.fit * this.zoom;
  }

  layout() {
    if (!this.mapW) return;
    const { width, height } = this.app.screen;
    this.fit = Math.min(width / this.mapW, height / this.mapH);
    this.cover = Math.max(width / this.mapW, height / this.mapH);
    this.app.stage.hitArea = this.app.screen;
    this.clampCenter();
  }

  /** Whole map visible, centred. */
  showWholeMap() {
    this.zoom = 1;
    this.center = { x: this.mapW / 2, y: this.mapH / 2 };
    this.follow = false;
  }

  /** Default view: close enough to see the characters, framing where the villagers are. */
  frameVillagers(agents: AgentBrief[], maxScale = DEFAULT_MAX_SCALE) {
    const alive = agents.filter((a) => a.alive);
    const pts = (alive.length ? alive : agents).map((a) => ({ x: a.x * UNIT, y: a.y * UNIT }));
    this.follow = false;
    if (!pts.length) {
      this.zoom = this.cover / this.fit;
      this.center = { x: this.mapW / 2, y: this.mapH / 2 };
      return;
    }
    const pad = 70;
    const x0 = Math.min(...pts.map((p) => p.x)) - pad;
    const x1 = Math.max(...pts.map((p) => p.x)) + pad;
    const y0 = Math.min(...pts.map((p) => p.y)) - pad;
    const y1 = Math.max(...pts.map((p) => p.y)) + pad;
    const { width, height } = this.app.screen;
    const target = Math.max(this.cover, Math.min(maxScale, width / (x1 - x0), height / (y1 - y0)));
    this.zoom = Math.max(1, Math.min(8, target / this.fit));
    this.center = { x: (x0 + x1) / 2, y: (y0 + y1) / 2 };
    this.clampCenter();
  }

  /** Focus on a conversation's agents (or clear the focus with null). */
  setFocus(ids: string[] | null) {
    const key = ids ? [...ids].sort().join(',') : '';
    if (key === this.focusKey) return;
    this.focusKey = key;
    this.focus = ids && ids.length ? new Set(ids) : null;
    this.followGroup = !!this.focus;
    if (this.focus && this.world) {
      this.follow = false;
      this.frameVillagers(this.world.agents.filter((a) => this.focus!.has(a.id)), 3);
    }
    for (const n of this.agents.values()) this.styleAgent(n);
  }

  spawnEnvelope(from: string, to: string, now: number) {
    const g = makeEnvelope();
    this.fx.addChild(g);
    this.envelopes.push({ g, from, to, start: now });
  }

  zoomAt(factor: number, sx?: number, sy?: number) {
    const { width, height } = this.app.screen;
    sx ??= width / 2;
    sy ??= height / 2;
    const before = this.screenToWorld(sx, sy);
    this.zoom = Math.max(1, Math.min(8, this.zoom * factor));
    const s = this.scale();
    if (!this.follow) this.center = { x: before.x - (sx - width / 2) / s, y: before.y - (sy - height / 2) / s };
    this.clampCenter();
  }

  clampCenter() {
    const s = this.scale();
    const { width, height } = this.app.screen;
    const halfW = width / s / 2;
    const halfH = height / s / 2;
    const clamp = (v: number, half: number, size: number) => (half * 2 >= size ? size / 2 : Math.max(half, Math.min(size - half, v)));
    this.center = { x: clamp(this.center.x, halfW, this.mapW), y: clamp(this.center.y, halfH, this.mapH) };
  }

  screenToWorld(sx: number, sy: number) {
    const s = this.scale();
    const { width, height } = this.app.screen;
    return { x: this.center.x + (sx - width / 2) / s, y: this.center.y + (sy - height / 2) / s };
  }

  worldToScreen(wx: number, wy: number) {
    const s = this.scale();
    const { width, height } = this.app.screen;
    return { x: (wx - this.center.x) * s + width / 2, y: (wy - this.center.y) * s + height / 2 };
  }

  // ------------------------------------------------------------- terrain
  buildTerrain(world: WorldView) {
    const terrain = generateTerrain(world);
    this.mapW = terrain.cols * TILE;
    this.mapH = terrain.rows * TILE;
    const tiles = new Container();
    const grass1 = tileTexture('grass1');
    const grass2 = tileTexture('grass2');
    const dirt = tileTexture('dirt');
    for (let r = 0; r < terrain.rows; r++) {
      for (let c = 0; c < terrain.cols; c++) {
        const t = terrain.tiles[r * terrain.cols + c];
        const s = new Sprite(t === DIRT ? dirt : t === GRASS2 ? grass2 : grass1);
        s.position.set(c * TILE, r * TILE);
        tiles.addChild(s);
      }
    }
    // Bake the static ground into one texture: one draw call instead of thousands.
    const rt = RenderTexture.create({ width: this.mapW, height: this.mapH });
    rt.source.scaleMode = 'nearest';
    this.app.renderer.render({ container: tiles, target: rt });
    tiles.destroy({ children: true });
    const old = this.ground.texture;
    this.ground.texture = rt;
    if (old && old !== rt && old !== Texture.EMPTY) old.destroy(true);

    // Rebuild trees and props.
    for (const child of this.objects.removeChildren()) {
      if (!(child as any).__agent) child.destroy({ children: true });
    }
    for (const node of this.agents.values()) this.objects.addChild(node.body);
    const tree = tileTexture('tree');
    for (const t of terrain.trees) {
      const s = new Sprite(tree);
      s.anchor.set(0.5, 0.95);
      s.position.set(t.x * UNIT, t.y * UNIT);
      s.zIndex = t.y * UNIT;
      this.objects.addChild(s);
    }
    this.props = [];
    this.lights.removeChildren().forEach((c) => c.destroy());
    this.lightSprites = [];
    for (const loc of world.locations) {
      const handle = buildProp(loc, UNIT);
      if (!handle) continue;
      this.objects.addChild(handle.container);
      this.props.push({ handle, loc });
      for (const l of handle.lights) {
        const g = new Graphics();
        for (let i = 4; i >= 1; i--) g.circle(l.x, l.y, (l.radius * i) / 4).fill({ color: l.color, alpha: 0.09 });
        this.lights.addChild(g);
        this.lightSprites.push({ g, radius: l.radius });
      }
    }
    this.darkness.clear().rect(0, 0, this.mapW, this.mapH).fill({ color: 0x0b1030 });
    this.buildLocationLabels(world);
    this.layout();
    this.frameVillagers(world.agents);
  }

  buildLocationLabels(world: WorldView) {
    this.locLabels.removeChildren().forEach((c) => c.destroy({ children: true }));
    for (const loc of world.locations) {
      const t = new Text({
        text: loc.name,
        style: new TextStyle({ fontFamily: FONT, fontSize: 13, fill: 0xfff6dc, stroke: { color: 0x2b1d10, width: 3 } }),
      });
      t.anchor.set(0.5, 0);
      (t as any).__loc = loc;
      this.locLabels.addChild(t);
    }
  }

  // -------------------------------------------------------------- update
  update(world: WorldView, selectedId: string | null, tickIntervalMs: number, thoughts: ThoughtMode) {
    const key = `${world.id}:${world.width}x${world.height}:${world.locations.map((l) => `${l.id}@${l.x},${l.y}`).join('|')}`;
    this.world = world;
    this.selectedId = selectedId;
    this.thoughts = thoughts;
    if (key !== this.terrainKey) {
      this.terrainKey = key;
      this.buildTerrain(world);
    }
    // Market produce reflects current stock.
    for (const { handle, loc } of this.props) {
      const live = world.locations.find((l) => l.id === loc.id);
      if (handle.market && live) {
        drawMarket(handle.market, live.x * UNIT, live.y * UNIT, live.max_stock ? (live.stock ?? 0) / live.max_stock : 1);
      }
    }
    for (const t of this.locLabels.children as Text[]) {
      const loc = world.locations.find((l) => l.id === (t as any).__loc.id);
      if (!loc) continue;
      let detail = '';
      if (loc.type === 'food' && loc.stock !== null) detail = `  ${loc.stock} food · ${loc.price}t`;
      if (loc.type === 'workplace' && loc.capacity !== null) detail = `  ${loc.capacity} job${loc.capacity === 1 ? '' : 's'}`;
      t.text = loc.name + detail;
      (t as any).__loc = loc;
    }

    const now = performance.now();
    const seen = new Set<string>();
    const groups = new Map<string, string[]>();
    const cellOf = (a: AgentBrief) => `${Math.round(a.x / 2.5)}:${Math.round(a.y / 2.5)}`;
    for (const a of world.agents) groups.set(cellOf(a), [...(groups.get(cellOf(a)) ?? []), a.id]);
    for (const a of world.agents) {
      seen.add(a.id);
      let n = this.agents.get(a.id);
      if (!n) {
        n = this.createAgent(a);
        this.agents.set(a.id, n);
      }
      const prevTo = n.to;
      n.from = { ...n.pos };
      const group = groups.get(cellOf(a)) ?? [a.id];
      const off = crowdOffset(a.id, group.indexOf(a.id), group.length);
      n.to = { x: a.x * UNIT + off.dx, y: a.y * UNIT + off.dy };
      n.start = now;
      n.duration = Math.max(150, Math.min(900, tickIntervalMs * 0.85));
      if (Math.hypot(n.to.x - prevTo.x, n.to.y - prevTo.y) > 0.5) {
        n.row = directionRow(n.to.x - n.from.x, n.to.y - n.from.y, n.row);
      }
      if (a.alive && a.health < n.lastHealth - 3) n.hurtUntil = now + HURT_MS;
      n.lastHealth = a.health;
      n.data = a;
      this.styleAgent(n);
      if (a.said && a.said !== n.lastSaid) {
        this.setBubble(n, 'speech', a.said, now + SPEECH_MS);
        const to = a.said_to;
        if (to && this.agents.has(to) && (!this.focus || (this.focus.has(a.id) && this.focus.has(to)))) {
          this.spawnEnvelope(a.id, to, now);
        }
      }
      n.lastSaid = a.said;
      const wantThought = thoughts === 'all' || (thoughts === 'selected' && a.id === selectedId);
      const active = Array.from(this.agents.values()).filter((x) => x.thought).length;
      if (a.intention && a.intention !== n.lastIntention && a.alive && wantThought && (active < MAX_THOUGHTS || a.id === selectedId)) {
        this.setBubble(n, 'thought', a.intention, now + THOUGHT_MS);
      }
      n.lastIntention = a.intention;
    }
    for (const [id, n] of this.agents) {
      if (seen.has(id)) continue;
      n.body.destroy({ children: true });
      n.label.destroy({ children: true });
      n.speech?.destroy({ children: true });
      n.thought?.destroy({ children: true });
      this.agents.delete(id);
    }
  }

  createAgent(a: AgentBrief): AgentNode {
    const body = new Container();
    (body as any).__agent = true;
    const shadow = new Graphics().ellipse(0, 0, 6, 2.5).fill({ color: 0x000000, alpha: 0.3 });
    const halo = new Graphics().ellipse(0, 0, 10, 4).fill({ color: 0xb197fc, alpha: 0.35 });
    const ring = new Graphics().ellipse(0, 0, 9, 3.5).stroke({ width: 1.5, color: 0xfab005 });
    const focusRing = new Graphics().ellipse(0, 0, 11, 4.5).stroke({ width: 1.5, color: 0x38d9a9 });
    const sprite = new Sprite(frameTexture(a.sprite ?? 'human-worker-red', 0, 0));
    sprite.anchor.set(0.5, ANCHOR_Y);
    body.addChild(halo, shadow, focusRing, ring, sprite);
    body.eventMode = 'static';
    body.cursor = 'pointer';
    body.hitArea = { contains: (x: number, y: number) => x > -9 && x < 9 && y > -16 && y < 3 };
    body.on('pointertap', (e) => {
      e.stopPropagation();
      this.onSelect(a.id);
    });
    this.objects.addChild(body);

    const label = new Container();
    const name = new Text({
      text: a.name,
      style: new TextStyle({ fontFamily: FONT, fontSize: 12, fill: 0xffffff, stroke: { color: 0x1a1208, width: 3 } }),
    });
    name.anchor.set(0.5, 1);
    const dot = new Graphics();
    const bar = new Graphics();
    const emote = new Text({ text: '', style: new TextStyle({ fontSize: 13 }) });
    emote.anchor.set(0.5, 1);
    label.addChild(bar, name, dot, emote);
    this.agentLabels.addChild(label);
    const pos = { x: a.x * UNIT, y: a.y * UNIT };
    return {
      data: a, body, sprite, ring, focusRing, halo, label, name, dot, bar, emote,
      from: { ...pos }, to: { ...pos }, pos: { ...pos }, start: 0, duration: 1, row: 0, hurtUntil: 0,
      speech: null, speechUntil: 0, thought: null, thoughtUntil: 0, lastSaid: null, lastIntention: null,
      lastHealth: a.health,
    };
  }

  styleAgent(n: AgentNode) {
    const a = n.data;
    const selected = a.id === this.selectedId;
    n.ring.visible = selected;
    n.focusRing.visible = !!this.focus?.has(a.id);
    n.body.alpha = this.focus && !this.focus.has(a.id) ? DIMMED_ALPHA : 1;
    n.halo.visible = a.alive && a.existential_active;
    n.sprite.tint = a.alive ? 0xffffff : 0x8a8a8a;
    n.sprite.alpha = a.alive ? 1 : 0.75;
    n.name.text = a.controller === 'llm' ? `◆ ${a.name}` : a.name;
    n.name.style.fill = selected ? 0xffe066 : a.controller === 'llm' ? 0xe5dbff : 0xffffff;
    n.dot.clear().circle(0, 0, 3.5).fill({ color: a.alive ? MOOD_COLORS[a.mood] ?? MOOD_COLORS.neutral : MOOD_COLORS.dead })
      .stroke({ width: 1, color: 0x1a1208 });
    n.bar.clear();
    if (a.alive) {
      n.bar.rect(-12, 0, 24, 4).fill({ color: 0x1a1208 });
      n.bar.rect(-11, 1, (22 * Math.max(0, a.health)) / 100, 2)
        .fill({ color: a.health > 50 ? 0x51cf66 : a.health > 25 ? 0xfcc419 : 0xff6b6b });
    }
    const emote = a.alive ? ACTION_EMOTES[a.action] ?? '' : ACTION_EMOTES.dead;
    n.emote.text = a.traveling ? '' : emote;
    n.body.zIndex = n.pos.y + (selected ? 0.5 : 0);
  }

  setBubble(n: AgentNode, kind: 'speech' | 'thought', text: string, until: number) {
    const old = kind === 'speech' ? n.speech : n.thought;
    old?.destroy({ children: true });
    const b = makeBubble(text, kind);
    this.bubbles.addChild(b);
    if (kind === 'speech') {
      n.speech = b;
      n.speechUntil = until;
    } else {
      n.thought = b;
      n.thoughtUntil = until;
    }
  }

  // --------------------------------------------------------------- frame
  frame() {
    if (!this.world || !this.mapW) return;
    const now = performance.now();
    const s = this.scale();
    const selected = this.selectedId ? this.agents.get(this.selectedId) : undefined;
    if (this.follow && selected) {
      this.center = {
        x: this.center.x + (selected.pos.x - this.center.x) * 0.12,
        y: this.center.y + (selected.pos.y - this.center.y) * 0.12,
      };
      this.clampCenter();
    }
    if (this.followGroup && this.focus) {
      const members = [...this.focus].map((id) => this.agents.get(id)).filter((n): n is AgentNode => !!n);
      if (members.length) {
        const cx = members.reduce((sum, n) => sum + n.pos.x, 0) / members.length;
        const cy = members.reduce((sum, n) => sum + n.pos.y, 0) / members.length;
        this.center = { x: this.center.x + (cx - this.center.x) * 0.06, y: this.center.y + (cy - this.center.y) * 0.06 };
        this.clampCenter();
      }
    }
    const { width, height } = this.app.screen;
    this.root.scale.set(s);
    this.root.position.set(Math.round(width / 2 - this.center.x * s), Math.round(height / 2 - this.center.y * s));

    // Day and night.
    const night = nightAlpha(this.world.tick, this.world.ticks_per_day);
    this.darkness.alpha = night;
    this.lights.alpha = Math.min(1, night * 2.2);
    for (const { handle, loc } of this.props) {
      if (handle.flame) drawFlame(handle.flame, loc.x * UNIT, loc.y * UNIT - 1, now);
    }
    const flicker = 0.85 + Math.sin(now * 0.017) * 0.08 + Math.sin(now * 0.041) * 0.05;
    for (const l of this.lightSprites) if (l.radius > 30) l.g.alpha = flicker;

    for (const t of this.locLabels.children as Text[]) {
      const loc = (t as any).__loc;
      const p = this.worldToScreen(loc.x * UNIT, loc.y * UNIT + loc.radius * UNIT * 0.7);
      t.position.set(Math.round(p.x), Math.round(p.y));
      t.visible = s > 0.5;
    }

    const crowded = this.agents.size > CROWDED_AGENTS;
    for (const n of this.agents.values()) {
      const t = Math.min(1, (now - n.start) / n.duration);
      const k = ease(t);
      n.pos.x = n.from.x + (n.to.x - n.from.x) * k;
      n.pos.y = n.from.y + (n.to.y - n.from.y) * k;
      const moving = t < 1 && Math.hypot(n.to.x - n.from.x, n.to.y - n.from.y) > 0.5;
      n.body.position.set(n.pos.x, n.pos.y);
      n.body.zIndex = n.pos.y + (n.data.id === this.selectedId ? 0.5 : 0);

      const a = n.data;
      const anim = now < n.hurtUntil ? 'hurt' : animFor(a.action, a.alive, moving);
      const spec = ANIMS[anim];
      const frame = spec.frames[Math.floor((now / 1000) * spec.fps) % spec.frames.length];
      const row = anim === 'lie' ? 0 : n.row;
      n.sprite.texture = frameTexture(a.sprite ?? 'human-worker-red', frame, row);

      // Screen-space label above the head.
      const head = this.worldToScreen(n.pos.x, n.pos.y - 16);
      const dimmed = !!this.focus && !this.focus.has(a.id);
      const showLabel = !dimmed && (!crowded || a.id === this.selectedId || !!this.focus);
      n.label.visible = showLabel;
      n.label.position.set(Math.round(head.x), Math.round(head.y));
      n.name.position.set(0, -6);
      n.dot.position.set(-n.name.width / 2 - 7, -12);
      n.bar.position.set(0, -4);
      n.emote.position.set(n.name.width / 2 + 10, -4);
      n.emote.visible = !!n.emote.text;

      const above = n.label.visible ? 24 : 6;
      if (n.speech) {
        if (now > n.speechUntil) {
          n.speech.destroy({ children: true });
          n.speech = null;
        } else {
          n.speech.position.set(head.x, head.y - above);
          n.speech.alpha = Math.min(1, (n.speechUntil - now) / 600);
          n.speech.visible = !dimmed;
        }
      }
      if (n.thought) {
        const keep = this.thoughts === 'all' || (this.thoughts === 'selected' && a.id === this.selectedId);
        if (now > n.thoughtUntil || !keep) {
          n.thought.destroy({ children: true });
          n.thought = null;
        } else {
          n.thought.position.set(head.x, head.y - above - (n.speech ? n.speech.height + 4 : 0));
          n.thought.alpha = Math.min(0.95, (n.thoughtUntil - now) / 600);
          n.thought.visible = !dimmed;
        }
      }
    }
    this.animateEnvelopes(now);
    this.separateBubbles();
  }

  animateEnvelopes(now: number) {
    // Never smaller than ~14 screen px, whatever the zoom.
    const size = Math.max(1, 14 / (8 * this.scale()));
    this.envelopes = this.envelopes.filter((e) => {
      const from = this.agents.get(e.from);
      const to = this.agents.get(e.to);
      const t = (now - e.start) / ENVELOPE_MS;
      if (!from || !to || t >= 1) {
        e.g.destroy();
        return false;
      }
      const k = ease(Math.max(0, t));
      const x = from.pos.x + (to.pos.x - from.pos.x) * k;
      const y = from.pos.y - 14 + (to.pos.y - from.pos.y) * k - Math.sin(Math.PI * k) * 14;
      e.g.position.set(x, y);
      e.g.rotation = Math.sin(t * Math.PI * 4) * 0.15;
      e.g.scale.set(size);
      e.g.alpha = t > 0.85 ? (1 - t) / 0.15 : 1;
      return true;
    });
  }

  /** Nudge overlapping bubbles upwards so every line stays readable. */
  separateBubbles() {
    const items = (this.bubbles.children as Container[]).filter((b) => b.visible).map((b) => {
      const { w, h } = (b as any).__size as { w: number; h: number };
      return { b, w, h, x: b.position.x, bottom: b.position.y };
    });
    items.sort((p, q) => q.bottom - p.bottom);
    const placed: typeof items = [];
    for (const it of items) {
      let moved = true;
      while (moved) {
        moved = false;
        for (const p of placed) {
          const overlapX = Math.abs(it.x - p.x) < (it.w + p.w) / 2 + 2;
          const overlapY = it.bottom > p.bottom - p.h - 2 && it.bottom - it.h < p.bottom;
          if (overlapX && overlapY) {
            it.bottom = p.bottom - p.h - 2;
            moved = true;
          }
        }
      }
      it.b.position.set(Math.round(it.x), Math.round(it.bottom));
      placed.push(it);
    }
  }

  destroy() {
    this.removeWheel();
  }
}

export function WorldCanvas({ world, selectedId, onSelect, tickIntervalMs, thoughts, focus = null, onClearFocus }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<Scene | null>(null);
  const latest = useRef({ world, selectedId, tickIntervalMs, thoughts });
  latest.current = { world, selectedId, tickIntervalMs, thoughts };
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [follow, setFollow] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let initialised = false;
    const app = new Application();
    Promise.all([
      app.init({
        resizeTo: host, background: 0x1c2e1b, antialias: false, autoDensity: true, roundPixels: true,
        resolution: Math.min(2, window.devicePixelRatio || 1),
      }),
      loadSpriteTextures(),
      document.fonts?.load(`12px ${FONT}`).catch(() => undefined),
    ]).then(() => {
      initialised = true;
      if (disposed) {
        app.destroy(true, { children: true });
        return;
      }
      host.appendChild(app.canvas);
      const scene = new Scene(app, host, (id) => onSelectRef.current(id));
      sceneRef.current = scene;
      const l = latest.current;
      if (l.world) scene.update(l.world, l.selectedId, l.tickIntervalMs, l.thoughts);
      setReady(true);
    });
    return () => {
      disposed = true;
      sceneRef.current?.destroy();
      sceneRef.current = null;
      if (initialised) app.destroy(true, { children: true });
    };
  }, []);

  useEffect(() => {
    if (world && sceneRef.current) sceneRef.current.update(world, selectedId, tickIntervalMs, thoughts);
  }, [world, selectedId, tickIntervalMs, thoughts, ready]);

  useEffect(() => {
    if (sceneRef.current) sceneRef.current.follow = follow && !!selectedId;
  }, [follow, selectedId, ready]);

  const focusKey = focus ? [...focus].sort().join(',') : '';
  useEffect(() => {
    if (focus?.length) setFollow(false);
    sceneRef.current?.setFocus(focus?.length ? focus : null);
  }, [focusKey, ready]);
  const focusNames = (focus ?? []).map((id) => world?.agents.find((a) => a.id === id)?.name ?? id);

  const zoom = (f: number) => sceneRef.current?.zoomAt(f);
  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <div ref={hostRef} style={{ position: 'absolute', inset: 0 }} aria-label="World map" role="img" />
      {focusNames.length > 0 && (
        <Group gap={6} wrap="nowrap" px={10} py={4}
          style={{ position: 'absolute', left: 8, top: 8, maxWidth: 'calc(100% - 180px)', borderRadius: 6,
            background: 'rgba(20, 30, 24, 0.85)', color: '#e6fcf5', border: '1px solid #38d9a9' }}>
          <MText size="xs" fw={600} truncate>💬 {focusNames.join(' · ')}</MText>
          <Tooltip label="Keep the conversation in view">
            <ActionIcon size="sm" variant="subtle" color="teal" aria-label="Follow conversation"
              onClick={() => sceneRef.current && (sceneRef.current.followGroup = true)}>◎</ActionIcon>
          </Tooltip>
          {onClearFocus && (
            <Tooltip label="Stop focusing">
              <ActionIcon size="sm" variant="subtle" color="gray" aria-label="Stop focusing on the conversation" onClick={onClearFocus}>✕</ActionIcon>
            </Tooltip>
          )}
        </Group>
      )}
      <Group gap={4} style={{ position: 'absolute', right: 8, top: 8 }}>
        <Tooltip label="Zoom in (or mouse wheel)"><ActionIcon variant="filled" color="dark" onClick={() => zoom(1.4)} aria-label="Zoom in">+</ActionIcon></Tooltip>
        <Tooltip label="Zoom out"><ActionIcon variant="filled" color="dark" onClick={() => zoom(1 / 1.4)} aria-label="Zoom out">−</ActionIcon></Tooltip>
        <Tooltip label="Reset the view">
          <ActionIcon variant="filled" color="dark" onClick={() => { setFollow(false); sceneRef.current?.showWholeMap(); }} aria-label="Show whole map">⤢</ActionIcon>
        </Tooltip>
        <Tooltip label={selectedId ? 'Follow the selected agent' : 'Select an agent to follow'}>
          <ActionIcon variant={follow && selectedId ? 'filled' : 'light'} color={follow && selectedId ? 'yellow' : 'gray'}
            disabled={!selectedId} aria-label="Follow selected agent"
            onClick={() => { const next = !follow; setFollow(next); if (next) sceneRef.current?.zoomAt(2.5 / (sceneRef.current?.zoom ?? 1)); }}>
            ◎
          </ActionIcon>
        </Tooltip>
      </Group>
    </div>
  );
}
