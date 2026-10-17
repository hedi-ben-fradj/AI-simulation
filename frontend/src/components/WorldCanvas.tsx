import { useEffect, useRef } from 'react';
import { Application, Container, Graphics, Text } from 'pixi.js';
import type { AgentBrief, Location, WorldView } from '../types';
import { LOCATION_COLORS, LOCATION_ICONS, MOOD_COLORS } from '../theme';

interface Props {
  world: WorldView | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  // Expected time between ticks; movement is interpolated over (most of) it.
  tickIntervalMs: number;
  thoughts: ThoughtMode;
}

export type ThoughtMode = 'off' | 'selected' | 'all';

const GROUND = 0x1d2621;
const SPEECH_MS = 4500;
const THOUGHT_MS = 3000;
// At most this many intention bubbles at once (the selected agent always gets one).
const MAX_THOUGHTS = 3;
const CROWDED_AGENTS = 40;

interface AgentSprite {
  root: Container;
  body: Graphics;
  label: Text;
  action: Text;
  from: { x: number; y: number };
  to: { x: number; y: number };
  pos: { x: number; y: number };
  start: number;
  duration: number;
  data: AgentBrief;
  speech: Container | null;
  speechUntil: number;
  thought: Container | null;
  thoughtUntil: number;
  lastSaid: string | null;
  lastIntention: string | null;
}

// Agents standing at the same spot are fanned out slightly (visual only).
function visualOffset(id: string, crowd: number): { dx: number; dy: number } {
  if (crowd <= 1) return { dx: 0, dy: 0 };
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  const angle = (h % 360) * (Math.PI / 180);
  const r = 2.2;
  return { dx: Math.cos(angle) * r, dy: Math.sin(angle) * r };
}

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

function makeBubble(text: string, kind: 'speech' | 'thought'): Container {
  const c = new Container();
  const t = new Text({
    text: text.length > 140 ? `${text.slice(0, 137)}…` : text,
    style: {
      fontFamily: 'system-ui, sans-serif',
      fontSize: 11,
      fill: kind === 'speech' ? 0x1b1b1b : 0xf1f3f5,
      fontStyle: kind === 'thought' ? 'italic' : 'normal',
      wordWrap: true,
      wordWrapWidth: 150,
      lineHeight: 14,
    },
  });
  const pad = 6;
  const g = new Graphics();
  const w = t.width + pad * 2;
  const h = t.height + pad * 2;
  if (kind === 'speech') {
    g.roundRect(0, 0, w, h, 6).fill({ color: 0xffffff, alpha: 0.95 });
    g.poly([w / 2 - 5, h, w / 2 + 5, h, w / 2, h + 6]).fill({ color: 0xffffff, alpha: 0.95 });
  } else {
    g.roundRect(0, 0, w, h, 10).fill({ color: 0x2b2f3a, alpha: 0.85 }).stroke({ width: 1, color: 0x9775fa, alpha: 0.8 });
    g.circle(w / 2, h + 5, 3).fill({ color: 0x2b2f3a, alpha: 0.85 });
  }
  t.position.set(pad, pad);
  c.addChild(g, t);
  c.pivot.set(w / 2, h + 8);
  return c;
}

class Scene {
  app: Application;
  ground = new Graphics();
  locLayer = new Container();
  agentLayer = new Container();
  bubbleLayer = new Container();
  agents = new Map<string, AgentSprite>();
  world: WorldView | null = null;
  scale = 1;
  ox = 0;
  oy = 0;
  selectedId: string | null = null;
  thoughts: ThoughtMode = 'all';
  tickIntervalMs = 500;
  onSelect: (id: string | null) => void;
  locKey = '';

  constructor(app: Application, onSelect: (id: string | null) => void) {
    this.app = app;
    this.onSelect = onSelect;
    this.agentLayer.sortableChildren = true;
    app.stage.addChild(this.ground, this.locLayer, this.agentLayer, this.bubbleLayer);
    app.stage.eventMode = 'static';
    app.stage.hitArea = app.screen;
    app.stage.on('pointertap', (e) => {
      if (e.target === app.stage) this.onSelect(null);
    });
    app.renderer.on('resize', () => this.layout());
    app.ticker.add(() => this.frame());
  }

  toScreen(x: number, y: number) {
    return { x: this.ox + x * this.scale, y: this.oy + y * this.scale };
  }

  layout() {
    if (!this.world) return;
    const { width, height } = this.app.screen;
    const pad = 30;
    this.scale = Math.min((width - pad * 2) / this.world.width, (height - pad * 2) / this.world.height);
    this.ox = (width - this.world.width * this.scale) / 2;
    this.oy = (height - this.world.height * this.scale) / 2;
    this.app.stage.hitArea = this.app.screen;
    this.drawGround();
    this.locKey = '';
    this.drawLocations(this.world.locations);
  }

  drawGround() {
    if (!this.world) return;
    const g = this.ground.clear();
    const tl = this.toScreen(0, 0);
    const w = this.world.width * this.scale;
    const h = this.world.height * this.scale;
    g.rect(tl.x, tl.y, w, h).fill({ color: GROUND }).stroke({ width: 1, color: 0x3a4a40 });
    const step = 10 * this.scale;
    for (let x = tl.x + step; x < tl.x + w - 1; x += step) g.moveTo(x, tl.y).lineTo(x, tl.y + h);
    for (let y = tl.y + step; y < tl.y + h - 1; y += step) g.moveTo(tl.x, y).lineTo(tl.x + w, y);
    g.stroke({ width: 1, color: 0x2a3630, alpha: 0.8 });
  }

  drawLocations(locations: Location[]) {
    const key = locations.map((l) => `${l.id}:${l.stock}:${l.occupancy}`).join('|') + `@${this.scale}`;
    if (key === this.locKey) return;
    this.locKey = key;
    this.locLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
    for (const loc of locations) {
      const color = LOCATION_COLORS[loc.type] ?? 0x868e96;
      const p = this.toScreen(loc.x, loc.y);
      const r = Math.max(10, loc.radius * this.scale);
      const g = new Graphics();
      g.circle(p.x, p.y, r).fill({ color, alpha: 0.18 }).stroke({ width: 2, color, alpha: 0.7 });
      const icon = new Text({ text: LOCATION_ICONS[loc.type] ?? '', style: { fontSize: 16, fill: color } });
      icon.anchor.set(0.5);
      icon.position.set(p.x, p.y);
      let detail = '';
      if (loc.type === 'food' && loc.stock !== null) detail = ` · ${loc.stock} food @ ${loc.price}`;
      if (loc.type === 'workplace' && loc.capacity !== null) detail = ` · cap ${loc.capacity}`;
      const label = new Text({
        text: `${loc.name}${detail}`,
        style: { fontFamily: 'system-ui, sans-serif', fontSize: 11, fill: 0xdee2e6 },
      });
      label.anchor.set(0.5, 0);
      label.position.set(p.x, p.y + r + 2);
      this.locLayer.addChild(g, icon, label);
    }
  }

  update(world: WorldView, selectedId: string | null, tickIntervalMs: number, thoughts: ThoughtMode) {
    const sizeChanged = !this.world || this.world.width !== world.width || this.world.height !== world.height;
    this.world = world;
    this.selectedId = selectedId;
    this.tickIntervalMs = tickIntervalMs;
    this.thoughts = thoughts;
    if (sizeChanged) this.layout();
    else this.drawLocations(world.locations);
    const now = performance.now();
    const seen = new Set<string>();
    const crowd = new Map<string, number>();
    const cell = (a: AgentBrief) => `${Math.round(a.x / 3)}:${Math.round(a.y / 3)}`;
    for (const a of world.agents) crowd.set(cell(a), (crowd.get(cell(a)) ?? 0) + 1);
    for (const a of world.agents) {
      seen.add(a.id);
      let s = this.agents.get(a.id);
      if (!s) {
        s = this.createAgent(a);
        this.agents.set(a.id, s);
      }
      s.from = { ...s.pos };
      const off = visualOffset(a.id, crowd.get(cell(a)) ?? 1);
      s.to = { x: a.x + off.dx, y: a.y + off.dy };
      s.start = now;
      s.duration = Math.max(120, Math.min(900, tickIntervalMs * 0.85));
      s.data = a;
      this.styleAgent(s);
      if (a.said && a.said !== s.lastSaid) {
        this.setBubble(s, 'speech', a.said, now + SPEECH_MS);
      }
      s.lastSaid = a.said;
      const wantThought = this.thoughts === 'all' || (this.thoughts === 'selected' && a.id === selectedId);
      const activeThoughts = Array.from(this.agents.values()).filter((x) => x.thought).length;
      const roomForThought = activeThoughts < MAX_THOUGHTS || a.id === selectedId;
      if (a.intention && a.intention !== s.lastIntention && a.alive && wantThought && roomForThought) {
        this.setBubble(s, 'thought', a.intention, now + THOUGHT_MS);
      }
      s.lastIntention = a.intention;
    }
    for (const [id, s] of this.agents) {
      if (!seen.has(id)) {
        s.root.destroy({ children: true });
        s.speech?.destroy({ children: true });
        s.thought?.destroy({ children: true });
        this.agents.delete(id);
      }
    }
  }

  setBubble(s: AgentSprite, kind: 'speech' | 'thought', text: string, until: number) {
    const old = kind === 'speech' ? s.speech : s.thought;
    old?.destroy({ children: true });
    const b = makeBubble(text, kind);
    this.bubbleLayer.addChild(b);
    if (kind === 'speech') {
      s.speech = b;
      s.speechUntil = until;
    } else {
      s.thought = b;
      s.thoughtUntil = until;
    }
  }

  createAgent(a: AgentBrief): AgentSprite {
    const root = new Container();
    const body = new Graphics();
    const label = new Text({
      text: a.name,
      style: { fontFamily: 'system-ui, sans-serif', fontSize: 11, fontWeight: '600', fill: 0xf8f9fa },
    });
    label.anchor.set(0.5, 0);
    label.position.set(0, 12);
    const action = new Text({ text: '', style: { fontFamily: 'system-ui, sans-serif', fontSize: 9, fill: 0xadb5bd } });
    action.anchor.set(0.5, 0);
    action.position.set(0, 25);
    root.addChild(body, label, action);
    root.eventMode = 'static';
    root.cursor = 'pointer';
    root.on('pointertap', (e) => {
      e.stopPropagation();
      this.onSelect(a.id);
    });
    this.agentLayer.addChild(root);
    const pos = { x: a.x, y: a.y };
    return {
      root, body, label, action, from: { ...pos }, to: { ...pos }, pos: { ...pos }, start: 0, duration: 1,
      data: a, speech: null, speechUntil: 0, thought: null, thoughtUntil: 0, lastSaid: null, lastIntention: null,
    };
  }

  styleAgent(s: AgentSprite) {
    const a = s.data;
    const g = s.body.clear();
    const color = a.alive ? MOOD_COLORS[a.mood] ?? MOOD_COLORS.neutral : MOOD_COLORS.dead;
    const selected = a.id === this.selectedId;
    if (selected) g.circle(0, 0, 15).fill({ color: 0xfab005, alpha: 0.25 }).stroke({ width: 2, color: 0xfab005 });
    if (a.existential_active && a.alive) g.circle(0, 0, 12).stroke({ width: 2, color: 0xb197fc, alpha: 0.9 });
    g.circle(0, 0, 8).fill({ color });
    if (a.controller === 'llm') g.circle(0, 0, 8).stroke({ width: 2, color: 0xffffff });
    if (!a.alive) {
      g.moveTo(-5, -5).lineTo(5, 5).moveTo(5, -5).lineTo(-5, 5).stroke({ width: 2, color: 0xced4da });
    } else {
      // Health bar
      g.rect(-9, -14, 18, 3).fill({ color: 0x343a40 });
      g.rect(-9, -14, (18 * Math.max(0, a.health)) / 100, 3).fill({ color: a.health > 50 ? 0x51cf66 : a.health > 25 ? 0xfcc419 : 0xff6b6b });
    }
    s.label.alpha = a.alive ? 1 : 0.5;
    // Crowded maps: only the selected agent keeps its labels.
    const crowded = (this.world?.agents.length ?? 0) > CROWDED_AGENTS;
    s.label.visible = !crowded || selected;
    s.action.visible = !crowded || selected;
    s.action.text = a.alive ? (a.traveling ? `→ ${a.action}` : a.action) : 'dead';
    s.root.zIndex = selected ? 10 : 0;
  }

  frame() {
    const now = performance.now();
    for (const s of this.agents.values()) {
      const t = Math.min(1, (now - s.start) / s.duration);
      const k = ease(t);
      s.pos.x = s.from.x + (s.to.x - s.from.x) * k;
      s.pos.y = s.from.y + (s.to.y - s.from.y) * k;
      const p = this.toScreen(s.pos.x, s.pos.y);
      s.root.position.set(p.x, p.y);
      if (s.speech) {
        if (now > s.speechUntil) {
          s.speech.destroy({ children: true });
          s.speech = null;
        } else {
          s.speech.position.set(p.x, p.y - 16);
          s.speech.alpha = Math.min(1, (s.speechUntil - now) / 600);
        }
      }
      if (s.thought) {
        const keep = this.thoughts === 'all' || (this.thoughts === 'selected' && s.data.id === this.selectedId);
        if (now > s.thoughtUntil || !keep) {
          s.thought.destroy({ children: true });
          s.thought = null;
        } else {
          const above = s.speech ? s.speech.height + 4 : 0;
          s.thought.position.set(p.x, p.y - 16 - above);
          s.thought.alpha = Math.min(0.95, (s.thoughtUntil - now) / 600);
        }
      }
    }
  }
}

export function WorldCanvas({ world, selectedId, onSelect, tickIntervalMs, thoughts }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<Scene | null>(null);
  const latest = useRef({ world, selectedId, tickIntervalMs, thoughts });
  latest.current = { world, selectedId, tickIntervalMs, thoughts };
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let ready = false;
    const app = new Application();
    app
      .init({
        resizeTo: host,
        background: 0x141a17,
        antialias: true,
        autoDensity: true,
        resolution: Math.min(2, window.devicePixelRatio || 1),
      })
      .then(() => {
        ready = true;
        if (disposed) {
          app.destroy(true, { children: true });
          return;
        }
        host.appendChild(app.canvas);
        const scene = new Scene(app, (id) => onSelectRef.current(id));
        sceneRef.current = scene;
        const l = latest.current;
        if (l.world) scene.update(l.world, l.selectedId, l.tickIntervalMs, l.thoughts);
      });
    return () => {
      disposed = true;
      sceneRef.current = null;
      if (ready) app.destroy(true, { children: true });
    };
  }, []);

  useEffect(() => {
    if (world && sceneRef.current) sceneRef.current.update(world, selectedId, tickIntervalMs, thoughts);
  }, [world, selectedId, tickIntervalMs, thoughts]);

  return <div ref={hostRef} style={{ position: 'absolute', inset: 0 }} aria-label="World map" role="img" />;
}
