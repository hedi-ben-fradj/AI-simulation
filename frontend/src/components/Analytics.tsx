import { useMemo } from 'react';
import { Button, Card, Group, SimpleGrid, Table, Text, useComputedColorScheme } from '@mantine/core';
import {
  Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import type { Metrics } from '../types';
import { SERIES_DARK, SERIES_LIGHT } from '../theme';

interface Props {
  metrics: Metrics[];
  ticksPerDay: number;
}

// Action groups for the time-allocation chart (5 entities, fixed colour slots).
const ACTION_GROUPS: Record<string, string[]> = {
  economy: ['work', 'buy_food'],
  survival: ['eat', 'rest'],
  social: ['socialize', 'talk', 'give', 'offer_trade', 'accept_trade', 'reject_trade', 'steal'],
  mind: ['reflect', 'create', 'study', 'explore'],
  'travel/idle': ['travel', 'move', 'idle'],
};

const MAX_POINTS = 400;

function downsample<T>(rows: T[]): T[] {
  if (rows.length <= MAX_POINTS) return rows;
  const step = Math.ceil(rows.length / MAX_POINTS);
  return rows.filter((_, i) => i % step === 0 || i === rows.length - 1);
}

interface SeriesSpec {
  key: string;
  label: string;
}

function ChartCard({ title, data, series, xKey, yDomain, colors, area = false, stacked = false, unit, daily = false }: {
  title: string;
  data: Record<string, number>[];
  series: SeriesSpec[];
  xKey: string;
  yDomain?: [number, number];
  colors: string[];
  area?: boolean;
  stacked?: boolean;
  unit?: string;
  daily?: boolean;
}) {
  const grid = 'var(--mantine-color-default-border)';
  const ink = 'var(--mantine-color-dimmed)';
  const tooltipStyle = {
    background: 'var(--mantine-color-body)', border: `1px solid ${grid}`, borderRadius: 6, fontSize: 12,
  };
  const axis = { stroke: grid, tick: { fill: ink, fontSize: 11 }, tickLine: false };
  return (
    <Card withBorder padding="sm">
      <Text size="sm" fw={600} mb={4}>{title}</Text>
      <ResponsiveContainer width="100%" height={190}>
        {area ? (
          <AreaChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke={grid} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey={xKey} {...axis} />
            <YAxis domain={yDomain ?? ['auto', 'auto']} {...axis} unit={unit} />
            <Tooltip contentStyle={tooltipStyle} />
            {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
            {series.map((s, i) => (
              <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stackId={stacked ? '1' : undefined}
                stroke={colors[i]} fill={colors[i]} fillOpacity={stacked ? 0.85 : 0.15} strokeWidth={stacked ? 1 : 2}
                isAnimationActive={false} />
            ))}
          </AreaChart>
        ) : (
          <LineChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke={grid} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey={xKey} {...axis} />
            <YAxis domain={yDomain ?? ['auto', 'auto']} {...axis} unit={unit} />
            <Tooltip contentStyle={tooltipStyle} />
            {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
            {series.map((s, i) => (
              <Line key={s.key} type={daily ? 'linear' : 'monotone'} dataKey={s.key} name={s.label} stroke={colors[i]}
                strokeWidth={2} dot={daily ? { r: 4 } : false} activeDot={{ r: 5 }} isAnimationActive={false} />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </Card>
  );
}

export function metricsToCsv(metrics: Metrics[]): string {
  if (!metrics.length) return '';
  const flat = metrics.map((m) => {
    const row: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(m)) {
      if (v && typeof v === 'object') for (const [k2, v2] of Object.entries(v)) row[`${k}.${k2}`] = v2;
      else row[k] = v;
    }
    return row;
  });
  const cols = Array.from(new Set(flat.flatMap((r) => Object.keys(r))));
  const esc = (v: unknown) => (v === undefined || v === null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  return [cols.join(','), ...flat.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n');
}

export function Analytics({ metrics, ticksPerDay }: Props) {
  const scheme = useComputedColorScheme('light');
  const colors = scheme === 'dark' ? SERIES_DARK : SERIES_LIGHT;

  const perTick = useMemo(() => downsample(metrics.map((m) => {
    const groups: Record<string, number> = {};
    for (const [g, acts] of Object.entries(ACTION_GROUPS)) groups[g] = acts.reduce((s, a) => s + (m.actions?.[a] ?? 0), 0);
    return {
      tick: m.tick,
      alive: m.alive,
      deaths: m.deaths_total,
      tokens: m.tokens_mean,
      gini: m.tokens_gini,
      hunger: m.hunger_mean,
      energy: m.energy_mean,
      health: m.health_mean,
      happiness: m.happiness_mean,
      stress: m.stress_mean,
      loneliness: m.loneliness_mean,
      trust: m.trust_mean,
      spend: (m.llm_spend_usd as number | undefined) ?? 0,
      ...groups,
    };
  })), [metrics]);

  const perDay = useMemo(() => {
    const days = new Map<number, Record<string, number>>();
    for (const m of metrics) {
      const d = Math.floor(m.tick / ticksPerDay) + 1;
      const row = days.get(d) ?? { day: d, messages: 0, trades: 0, gifts: 0, thefts: 0, activations: 0, reflections: 0, existential_messages: 0, refusals: 0 };
      row.messages += m.messages_sent;
      row.trades += m.trades + m.help_given;
      row.gifts += m.gifts;
      row.thefts += m.thefts;
      row.refusals += m.refusals;
      row.activations += m.existential_activations;
      row.reflections += m.existential_reflections;
      row.existential_messages += m.existential_messages;
      days.set(d, row);
    }
    return Array.from(days.values());
  }, [metrics, ticksPerDay]);

  const latest = metrics[metrics.length - 1];
  const download = () => {
    const blob = new Blob([metricsToCsv(metrics)], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'metrics.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (!metrics.length) return <Text c="dimmed" size="sm">No metrics yet — run the world for a few ticks.</Text>;

  const hasSpend = perTick.some((r) => r.spend > 0);
  return (
    <>
      <Group justify="space-between" mb="sm">
        <Text size="sm" c="dimmed">{metrics.length} ticks recorded · charts show up to {MAX_POINTS} points</Text>
        <Button size="xs" variant="default" onClick={download}>Download metrics CSV</Button>
      </Group>
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="sm">
        <ChartCard title="Population" data={perTick} xKey="tick" colors={colors}
          series={[{ key: 'alive', label: 'Alive' }, { key: 'deaths', label: 'Deaths (cumulative)' }]} />
        <ChartCard title="Needs (mean, 0–100)" data={perTick} xKey="tick" colors={colors} yDomain={[0, 100]}
          series={[{ key: 'health', label: 'Health' }, { key: 'energy', label: 'Energy' }, { key: 'hunger', label: 'Hunger' }]} />
        <ChartCard title="Well-being (mean, 0–1)" data={perTick} xKey="tick" colors={colors} yDomain={[0, 1]}
          series={[{ key: 'happiness', label: 'Happiness' }, { key: 'stress', label: 'Stress' }, { key: 'loneliness', label: 'Loneliness' }]} />
        <ChartCard title="Mean tokens per agent" data={perTick} xKey="tick" colors={colors}
          series={[{ key: 'tokens', label: 'Tokens' }]} area />
        <ChartCard title="Token inequality (Gini)" data={perTick} xKey="tick" colors={colors.slice(1)} yDomain={[0, 1]}
          series={[{ key: 'gini', label: 'Gini' }]} />
        <ChartCard title="What agents are doing (agents per activity)" data={perTick} xKey="tick" colors={colors}
          series={Object.keys(ACTION_GROUPS).map((g) => ({ key: g, label: g }))} area stacked />
        <ChartCard title="Social interactions per day" data={perDay} xKey="day" colors={colors} daily
          series={[{ key: 'messages', label: 'Messages' }, { key: 'trades', label: 'Trades & help' }, { key: 'gifts', label: 'Gifts' }, { key: 'thefts', label: 'Thefts' }]} />
        <ChartCard title="Mean directed trust" data={perTick} xKey="tick" colors={colors.slice(2)} yDomain={[0, 1]}
          series={[{ key: 'trust', label: 'Trust' }]} />
        <ChartCard title="Existential activity per day" data={perDay} xKey="day" colors={colors.slice(6)} daily
          series={[{ key: 'activations', label: 'Activations' }, { key: 'reflections', label: 'Reflections' }]} />
        {hasSpend && (
          <ChartCard title="Cumulative LLM spend (USD, real cost)" data={perTick} xKey="tick" colors={colors.slice(3)}
            series={[{ key: 'spend', label: 'USD' }]} area />
        )}
      </SimpleGrid>
      {latest && (
        <Card withBorder padding="sm" mt="sm">
          <Text size="sm" fw={600} mb={4}>Latest values (tick {latest.tick})</Text>
          <Table fz="xs" withColumnBorders>
            <Table.Tbody>
              <Table.Tr>
                <Table.Td>Alive {latest.alive}/{latest.population}</Table.Td>
                <Table.Td>Deaths: {Object.entries(latest.deaths_by_cause).map(([k, v]) => `${k} ${v}`).join(', ') || 'none'}</Table.Td>
                <Table.Td>Mean tokens {latest.tokens_mean.toFixed(1)} · Gini {latest.tokens_gini.toFixed(2)}</Table.Td>
                <Table.Td>Food in stock {latest.food_stock_total}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Health {latest.health_mean.toFixed(0)} · Energy {latest.energy_mean.toFixed(0)} · Hunger {latest.hunger_mean.toFixed(0)}</Table.Td>
                <Table.Td>Happiness {latest.happiness_mean.toFixed(2)} · Stress {latest.stress_mean.toFixed(2)}</Table.Td>
                <Table.Td>Trust {latest.trust_mean.toFixed(2)}</Table.Td>
                <Table.Td>{latest.llm_spend_usd !== undefined ? `LLM spend $${Number(latest.llm_spend_usd).toFixed(4)}` : 'Rule-based'}</Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </>
  );
}
