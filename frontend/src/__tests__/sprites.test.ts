import { describe, expect, it } from 'vitest';
import { animFor, archetypeOf, directionRow } from '../sprites';
import { DIRT, generateTerrain, nightAlpha } from '../terrain';

describe('directionRow', () => {
  it('maps movement to the sheet rows S, SE, E, NE, N, NW, W, SW', () => {
    expect(directionRow(0, 1)).toBe(0);
    expect(directionRow(1, 1)).toBe(1);
    expect(directionRow(1, 0)).toBe(2);
    expect(directionRow(1, -1)).toBe(3);
    expect(directionRow(0, -1)).toBe(4);
    expect(directionRow(-1, -1)).toBe(5);
    expect(directionRow(-1, 0)).toBe(6);
    expect(directionRow(-1, 1)).toBe(7);
  });

  it('keeps the previous facing when standing still', () => {
    expect(directionRow(0, 0, 5)).toBe(5);
  });
});

describe('animations and archetypes', () => {
  it('picks animations from state', () => {
    expect(animFor('work', false, false)).toBe('lie');
    expect(animFor('work', true, true)).toBe('walk');
    expect(animFor('work', true, false)).toBe('work');
    expect(animFor('steal', true, false)).toBe('swing');
    expect(animFor('talk', true, false)).toBe('stand');
  });

  it('strips colour variants', () => {
    expect(archetypeOf('mage-cyan')).toBe('mage');
    expect(archetypeOf('human-worker-red')).toBe('human-worker');
    expect(archetypeOf('orc-grunt')).toBe('orc');
    expect(archetypeOf(undefined)).toBe('human-worker');
  });
});

describe('terrain', () => {
  const world = {
    id: 'abc123', width: 60, height: 40,
    locations: [
      { id: 'a', name: 'A', type: 'food', x: 10, y: 10, radius: 4 },
      { id: 'b', name: 'B', type: 'workplace', x: 50, y: 30, radius: 4 },
    ],
  } as any;

  it('is deterministic per world', () => {
    const t1 = generateTerrain(world);
    const t2 = generateTerrain(world);
    expect(Array.from(t1.tiles)).toEqual(Array.from(t2.tiles));
    expect(t1.trees).toEqual(t2.trees);
    expect(t1.cols).toBe(30);
    expect(t1.rows).toBe(20);
  });

  it('puts dirt under locations and keeps trees off them', () => {
    const t = generateTerrain(world);
    for (const loc of world.locations) {
      expect(t.tiles[Math.floor(loc.y / 2) * t.cols + Math.floor(loc.x / 2)]).toBe(DIRT);
      expect(t.trees.every((p) => Math.hypot(p.x - loc.x, p.y - loc.y) > loc.radius)).toBe(true);
    }
  });

  it('is dark at night and clear by day', () => {
    expect(nightAlpha(12, 24)).toBe(0);
    expect(nightAlpha(0, 24)).toBe(0.5);
  });
});
