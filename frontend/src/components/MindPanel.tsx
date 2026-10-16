import { useEffect, useMemo, useState } from 'react';
import {
  Accordion, Badge, Card, Grid, MultiSelect, ScrollArea, Stack, Table, Text, Tooltip, useComputedColorScheme,
} from '@mantine/core';
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import type { Metrics } from '../types';
import { SERIES_DARK, SERIES_LIGHT, trustColor } from '../theme';

interface Hypothesis { trait: string; behaviour: string; expected_sign: number; r: number | null; n: number; supported: boolean | null }
interface Analysis {
  tick: number;
  caveat: string;
  correlations: { n: number; behaviours: string[]; matrix: Record<string, Record<string, number | null>>; hypotheses: Hypothesis[] };
  behaviour: { agent_id: string; name: string; traits: Record<string, number>; behaviour: Record<string, number> }[];
  existential: {
    activation_rate: number;
    agents_with_beliefs: number;
    per_agent: { agent_id: string; name: string; alive: boolean; spirituality: number; activation_rate: number; ticks_contemplating: number;
      conversations: number; beliefs: { tick: number; text: string }[]; belief_revisions: number }[];
  };
}

interface Props {
  worldId: string;
  tick: number;
  metrics: Metrics[];
  onSelectAgent: (id: string) => void;
}

const pretty = (s: string) => s.replace(/_/g, ' ');

export function MindPanel({ worldId, tick, metrics, onSelectAgent }: Props) {
  const scheme = useComputedColorScheme('light');
  const colors = scheme === 'dark' ? SERIES_DARK : SERIES_LIGHT;
  const [data, setData] = useState<Analysis | null>(null);
  const [traits, setTraits] = useState<string[]>(['spirituality', 'generosity', 'agreeableness']);

  useEffect(() => {
    const t = setTimeout(() => {
      api.analysis<Analysis>(worldId).then(setData).catch(() => undefined);
    }, 300);
    return () => clearTimeout(t);
  }, [worldId, Math.floor(tick / 6)]);

  const drift = useMemo(() => {
    const step = Math.max(1, Math.ceil(metrics.length / 300));
    return metrics.filter((_, i) => i % step === 0).map((m) => {
      const tm = (m.traits_mean ?? {}) as Record<string, number>;
      return { tick: m.tick, ...Object.fromEntries(traits.map((t) => [t, tm[t]])) };
    });
  }, [metrics, traits]);

  if (!data) return <Text size="sm" c="dimmed">Loading analysis…</Text>;
  const { correlations: corr, existential: ex } = data;
  const scatter = ex.per_agent.filter((p) => p.activation_rate !== undefined).map((p) => ({
    spirituality: p.spirituality, rate: p.activation_rate, name: p.name,
  }));
  const allTraits = Object.keys(corr.matrix);

  const grid = 'var(--mantine-color-default-border)';
  const axis = { stroke: grid, tick: { fill: 'var(--mantine-color-dimmed)', fontSize: 11 }, tickLine: false };
  const tooltipStyle = { background: 'var(--mantine-color-body)', border: `1px solid ${grid}`, borderRadius: 6, fontSize: 12 };

  return (
    <Stack gap="sm">
      <Text size="xs" c="dimmed">{data.caveat} Traits are birth values; n = {corr.n} agents with at least one day of history.</Text>
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="sm">
            <Text fw={600} size="sm" mb={4}>Do traits change behaviour? (pre-registered hypotheses)</Text>
            <Table fz="xs" striped verticalSpacing={4}>
              <Table.Thead>
                <Table.Tr><Table.Th>Trait</Table.Th><Table.Th>Behaviour</Table.Th><Table.Th>Expected</Table.Th><Table.Th>r</Table.Th><Table.Th>Verdict</Table.Th></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {corr.hypotheses.map((h) => (
                  <Table.Tr key={`${h.trait}-${h.behaviour}`}>
                    <Table.Td>{pretty(h.trait)}</Table.Td>
                    <Table.Td>{pretty(h.behaviour)}</Table.Td>
                    <Table.Td>{h.expected_sign > 0 ? '+' : '−'}</Table.Td>
                    <Table.Td>{h.r === null ? '–' : h.r.toFixed(2)}</Table.Td>
                    <Table.Td>
                      {h.supported === null ? <Badge size="xs" color="gray" variant="light">no variance</Badge>
                        : h.supported ? <Badge size="xs" color="teal" variant="light">supported</Badge>
                          : <Badge size="xs" color="orange" variant="light">not supported</Badge>}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            <Text size="xs" c="dimmed" mt={4}>“Supported” means |r| &gt; 0.2 in the expected direction in this run only.</Text>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="sm">
            <Text fw={600} size="sm">Spirituality vs. existential activation</Text>
            <Text size="xs" c="dimmed" mb={4}>
              Population activation rate {(ex.activation_rate * 100).toFixed(1)}% of decision opportunities · {ex.agents_with_beliefs} agent(s) stated a belief
            </Text>
            <ResponsiveContainer width="100%" height={230}>
              <ScatterChart margin={{ top: 8, right: 12, left: -8, bottom: 8 }}>
                <CartesianGrid stroke={grid} strokeDasharray="2 4" />
                <XAxis type="number" dataKey="spirituality" name="spirituality" domain={[0, 1]} {...axis}
                  label={{ value: 'spirituality (birth)', position: 'insideBottom', offset: -4, fontSize: 11, fill: 'var(--mantine-color-dimmed)' }} />
                <YAxis type="number" dataKey="rate" name="activation rate" {...axis} />
                <RTooltip contentStyle={tooltipStyle} formatter={(v: number) => v.toFixed(3)}
                  labelFormatter={() => ''} />
                <Scatter data={scatter} fill={colors[6]} />
              </ScatterChart>
            </ResponsiveContainer>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="sm">
            <Text fw={600} size="sm" mb={4}>Population trait drift (mean of living agents)</Text>
            <MultiSelect size="xs" data={allTraits.map((t) => ({ value: t, label: pretty(t) }))} value={traits}
              onChange={(v) => setTraits(v.slice(0, 3))} maxValues={3} mb={4} aria-label="Traits to plot" />
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={drift} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid stroke={grid} strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="tick" {...axis} />
                <YAxis domain={['auto', 'auto']} {...axis} />
                <RTooltip contentStyle={tooltipStyle} />
                {traits.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
                {traits.map((t, i) => (
                  <Line key={t} dataKey={t} name={pretty(t)} stroke={colors[i]} strokeWidth={2} dot={false} isAnimationActive={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="sm">
            <Text fw={600} size="sm" mb={4}>Beliefs about purpose (stated by agents)</Text>
            <ScrollArea h={250}>
              <Stack gap={6}>
                {ex.per_agent.filter((p) => p.beliefs.length).length === 0 && (
                  <Text size="xs" c="dimmed">No beliefs stated yet. Rule-based agents contemplate but do not state beliefs; LLM agents may.</Text>
                )}
                {ex.per_agent.filter((p) => p.beliefs.length).map((p) => (
                  <div key={p.agent_id}>
                    <Text size="xs" fw={600} style={{ cursor: 'pointer' }} onClick={() => onSelectAgent(p.agent_id)}>
                      {p.name} <Text span size="xs" c="dimmed">· {p.belief_revisions} revision(s) · {p.conversations} existential conversation(s)</Text>
                    </Text>
                    {p.beliefs.slice().reverse().map((b, i) => (
                      <Text key={i} size="xs" c={i === 0 ? undefined : 'dimmed'}>t{b.tick}: {b.text}</Text>
                    ))}
                  </div>
                ))}
              </Stack>
            </ScrollArea>
            <Text size="xs" c="dimmed" mt={4}>Model outputs, not evidence of consciousness.</Text>
          </Card>
        </Grid.Col>
      </Grid>
      <Accordion variant="contained">
        <Accordion.Item value="matrix">
          <Accordion.Control>Full trait × behaviour correlation matrix</Accordion.Control>
          <Accordion.Panel>
            <ScrollArea>
              <Table fz="xs" withColumnBorders verticalSpacing={2}>
                <Table.Thead>
                  <Table.Tr><Table.Th />{corr.behaviours.map((b) => <Table.Th key={b}>{pretty(b)}</Table.Th>)}</Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {allTraits.map((t) => (
                    <Table.Tr key={t}>
                      <Table.Td fw={600}>{pretty(t)}</Table.Td>
                      {corr.behaviours.map((b) => {
                        const r = corr.matrix[t][b];
                        return (
                          <Tooltip key={b} label={`${pretty(t)} × ${pretty(b)}: r = ${r === null ? 'n/a' : r.toFixed(2)}`}>
                            <Table.Td style={{ background: r === null ? undefined : trustColor((r + 1) / 2, scheme), textAlign: 'center' }}>
                              {r === null ? '–' : r.toFixed(2)}
                            </Table.Td>
                          </Tooltip>
                        );
                      })}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
            <Text size="xs" c="dimmed">Red = negative, blue = positive correlation.</Text>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
