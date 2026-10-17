import { describe, expect, it } from 'vitest';
import { trustColor } from '../theme';
import { metricsToCsv } from '../components/Analytics';

describe('trustColor', () => {
  it('is neutral at the prior and diverges to red/blue', () => {
    expect(trustColor(0.5, 'light')).toBe('#f0efec');
    expect(trustColor(0.0, 'light')).toBe('#e34948');
    expect(trustColor(1.0, 'light')).toBe('#2a78d6');
    expect(trustColor(0.65, 'dark')).not.toBe(trustColor(0.35, 'dark'));
  });
});

describe('metricsToCsv', () => {
  it('flattens nested objects and escapes values', () => {
    const csv = metricsToCsv([{ tick: 0, actions: { work: 2 }, note: 'a,b' } as any, { tick: 1, actions: { rest: 1 } } as any]);
    const [header, row1, row2] = csv.split('\n');
    expect(header.split(',')).toEqual(['tick', 'actions.work', 'note', 'actions.rest']);
    expect(row1).toBe('0,2,"a,b",');
    expect(row2).toBe('1,,,1');
  });
});
