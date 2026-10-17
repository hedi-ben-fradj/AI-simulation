import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Badge, Button, Card, Grid, Group, JsonInput, Modal, NumberInput, Progress, ScrollArea, Select, SimpleGrid,
  Stack, Table, Text, TextInput, Title, useComputedColorScheme,
} from '@mantine/core';
import {
  Bar, BarChart, CartesianGrid, Cell, ErrorBar, Legend, Line, LineChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import { SERIES_DARK, SERIES_LIGHT } from '../theme';

interface Props {
  onOpenWorld: (worldId: string) => void;
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'gray', running: 'blue', completed: 'teal', completed_with_errors: 'yellow', cancelled: 'orange',
  failed: 'red', interrupted: 'orange',
};

const KEY_METRICS: { key: string; label: string; pct?: boolean }[] = [
  { key: 'survival_rate', label: 'Survival rate', pct: true },
  { key: 'share_work', label: 'Time working', pct: true },
  { key: 'share_social', label: 'Time socialising', pct: true },
  { key: 'share_contemplation', label: 'Time contemplating', pct: true },
  { key: 'existential_activation_rate', label: 'Existential activation rate', pct: true },
  { key: 'final_trust_mean', label: 'Mean trust (end)' },
  { key: 'messages_per_agent_day', label: 'Messages per agent-day' },
  { key: 'thefts_per_agent_day', label: 'Thefts per agent-day' },
  { key: 'mean_health', label: 'Mean health' },
];

const SHARE_KEYS = ['work', 'rest', 'survival_chores', 'social', 'creative_scientific', 'contemplation', 'conflict', 'travel_idle'];

const pretty = (s: string) => s.replace(/_/g, ' ');

function fmt(v: number | null | undefined, pct = false): string {
  if (v === null || v === undefined) return '–';
  return pct ? `${(v * 100).toFixed(1)}%` : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(3);
}

function NewExperimentModal({ opened, onClose, onCreated }: { opened: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const [templates, setTemplates] = useState<any[]>([]);
  const [templateId, setTemplateId] = useState<string | null>('scarcity_vs_abundance');
  const [name, setName] = useState('');
  const [basePreset, setBasePreset] = useState('default');
  const [conditions, setConditions] = useState('[]');
  const [seeds, setSeeds] = useState('1, 2, 3');
  const [ticks, setTicks] = useState<number | string>(168);
  const [population, setPopulation] = useState<number | string>(5);
  const [provider, setProvider] = useState('none');
  const [parallel, setParallel] = useState<number | string>(2);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (opened) api.experimentTemplates().then(setTemplates).catch((e) => setError(String(e)));
  }, [opened]);

  useEffect(() => {
    const t = templates.find((x) => x.id === templateId);
    if (!t) return;
    setName(t.name);
    setBasePreset(t.base_preset);
    setConditions(JSON.stringify(t.conditions, null, 2));
    setSeeds(t.seeds.join(', '));
    setTicks(t.ticks);
  }, [templateId, templates]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const spec = {
        name,
        base_preset: basePreset,
        base_overrides: { simulation: { population: Number(population) }, llm: { provider } },
        conditions: JSON.parse(conditions),
        seeds: seeds.split(/[\s,]+/).filter(Boolean).map(Number),
        ticks: Number(ticks),
        parallel_runs: Number(parallel),
        description: templates.find((x) => x.id === templateId)?.description ?? '',
      };
      const exp = await api.createExperiment(spec);
      onCreated(exp.id);
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const runs = (() => {
    try {
      return JSON.parse(conditions).length * seeds.split(/[\s,]+/).filter(Boolean).length;
    } catch {
      return 0;
    }
  })();

  return (
    <Modal opened={opened} onClose={onClose} title="New experiment" size="xl">
      <Stack gap="sm">
        <Select label="Start from a design" data={templates.map((t) => ({ value: t.id, label: t.name }))}
          value={templateId} onChange={setTemplateId} />
        <Text size="sm" c="dimmed">{templates.find((x) => x.id === templateId)?.description}</Text>
        <Group grow>
          <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <TextInput label="Base preset" value={basePreset} onChange={(e) => setBasePreset(e.currentTarget.value)} />
        </Group>
        <JsonInput label="Conditions (each: name, optional preset, overrides)" value={conditions} onChange={setConditions}
          autosize minRows={6} maxRows={14} validationError="Invalid JSON" formatOnBlur />
        <Group grow>
          <TextInput label="Seeds" description="One run per seed per condition" value={seeds} onChange={(e) => setSeeds(e.currentTarget.value)} />
          <NumberInput label="Ticks per run" min={1} value={ticks} onChange={setTicks} />
          <NumberInput label="Population" min={1} max={20} value={population} onChange={setPopulation} />
        </Group>
        <Group grow>
          <Select label="Agent decisions" value={provider} onChange={(v) => v && setProvider(v)} allowDeselect={false}
            data={[{ value: 'none', label: 'Rule-based (fast, free, reproducible)' }, { value: 'mock', label: 'Mock LLM (offline)' },
              { value: 'anthropic', label: 'Anthropic Claude (API cost, capped)' }]} />
          <NumberInput label="Runs in parallel" min={1} max={8} value={parallel} onChange={setParallel} />
        </Group>
        {provider === 'anthropic' && (
          <Alert color="yellow">LLM experiments make real API calls: {runs} runs × {String(ticks)} ticks. Per-world and per-experiment spend caps apply.</Alert>
        )}
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="space-between">
          <Text size="sm" c="dimmed">{runs} run(s) in total</Text>
          <Group>
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Button loading={busy} onClick={submit}>Start experiment</Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}

function ConditionBar({ title, metric, pct, comparison, colors }: { title: string; metric: string; pct?: boolean; comparison: any; colors: string[] }) {
  const data = comparison.conditions.map((c: string) => {
    const e = comparison.metrics[metric]?.[c] ?? {};
    return { condition: c, mean: e.mean ?? 0, ci: e.ci95 ?? 0, p: e.vs_baseline?.p ?? null, n: e.n };
  });
  const grid = 'var(--mantine-color-default-border)';
  const axis = { stroke: grid, tick: { fill: 'var(--mantine-color-dimmed)', fontSize: 11 }, tickLine: false };
  return (
    <Card withBorder padding="sm">
      <Text size="sm" fw={600}>{title}</Text>
      <ResponsiveContainer width="100%" height={170}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={grid} strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="condition" {...axis} />
          {/* All measures are non-negative; shares and rates are bounded by 100%. */}
          <YAxis {...axis} domain={[0, pct ? 1 : 'auto']} allowDataOverflow
            tickFormatter={(v) => (pct ? `${Math.round(v * 100)}%` : String(Number(v.toPrecision(3))))} />
          <RTooltip contentStyle={{ background: 'var(--mantine-color-body)', border: `1px solid ${grid}`, borderRadius: 6, fontSize: 12 }}
            formatter={(_v: number, _n: string, item: any) => [
              `${fmt(item.payload.mean, pct)} ± ${fmt(item.payload.ci, pct)} (n=${item.payload.n})${item.payload.p !== null ? ` · p=${item.payload.p.toPrecision(2)}` : ''}`,
              'mean ± 95% CI']} />
          <Bar dataKey="mean" radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {data.map((_: any, i: number) => <Cell key={i} fill={colors[i % colors.length]} />)}
            <ErrorBar dataKey="ci" width={6} stroke="var(--mantine-color-text)" strokeWidth={1.5} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Card>
  );
}

function ExperimentDetail({ exp, onOpenWorld, onChanged, colors }: { exp: any; onOpenWorld: (id: string) => void; onChanged: () => void; colors: string[] }) {
  const results = exp.results;
  const comparison = results?.comparison;
  const series = results?.series ?? {};
  const [seriesKey, setSeriesKey] = useState('alive');
  const grid = 'var(--mantine-color-default-border)';
  const axis = { stroke: grid, tick: { fill: 'var(--mantine-color-dimmed)', fontSize: 11 }, tickLine: false };

  const overlay = useMemo(() => {
    const conds = Object.keys(series);
    if (!conds.length) return [];
    const len = Math.max(...conds.map((c) => series[c].length));
    return Array.from({ length: len }, (_, i) => {
      const row: Record<string, number> = { day: series[conds[0]][i]?.day ?? i + 1 };
      for (const c of conds) if (series[c][i]) row[c] = series[c][i][seriesKey];
      return row;
    });
  }, [series, seriesKey]);

  const shareData = comparison
    ? comparison.conditions.map((c: string) => ({
      condition: c, ...Object.fromEntries(SHARE_KEYS.map((k) => [k, comparison.metrics[`share_${k}`]?.[c]?.mean ?? 0])),
    }))
    : [];

  const running = exp.status === 'running' || exp.status === 'pending';
  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={4}>{exp.name}</Title>
          <Text size="sm" c="dimmed">{exp.description}</Text>
          <Text size="xs" c="dimmed">
            {exp.spec.conditions.length} condition(s) × seeds [{exp.spec.seeds.join(', ')}] × {exp.spec.ticks} ticks · base preset {exp.spec.base_preset}
            {results?.total_llm_spend_usd ? ` · LLM spend $${results.total_llm_spend_usd.toFixed(4)}` : ''}
          </Text>
        </div>
        <Group gap="xs">
          <Badge color={STATUS_COLOR[exp.status] ?? 'gray'} variant="light">{pretty(exp.status)}</Badge>
          {running && <Button size="xs" color="orange" variant="light" onClick={() => api.cancelExperiment(exp.id).then(onChanged)}>Cancel</Button>}
          <Button size="xs" variant="default" component="a" href={`/api/experiments/${exp.id}/export?kind=summary`}>Summary CSV</Button>
          <Button size="xs" variant="default" component="a" href={`/api/experiments/${exp.id}/export?kind=timeseries`}>Timeseries CSV</Button>
          <Button size="xs" variant="default" component="a" href={`/api/experiments/${exp.id}/export?format=json`}>JSON</Button>
          <Button size="xs" variant="subtle" color="red" onClick={() => {
            if (window.confirm('Delete this experiment and all of its runs?')) api.deleteExperiment(exp.id).then(onChanged);
          }}>Delete</Button>
        </Group>
      </Group>
      {running && <Progress value={(exp.progress ?? 0) * 100} animated striped aria-label="progress" />}
      {exp.error && <Alert color="red">{exp.error}</Alert>}
      {comparison && (
        <>
          <Text size="xs" c="dimmed">{comparison.note} Baseline: <b>{comparison.baseline}</b>.</Text>
          <SimpleGrid cols={{ base: 1, sm: 2, xl: 3 }} spacing="sm">
            {KEY_METRICS.map((m) => (
              <ConditionBar key={m.key} title={m.label} metric={m.key} pct={m.pct} comparison={comparison} colors={colors} />
            ))}
          </SimpleGrid>
          <Grid gutter="sm">
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Card withBorder padding="sm">
                <Text size="sm" fw={600}>How agents spend their time (mean share)</Text>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={shareData} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
                    <CartesianGrid stroke={grid} strokeDasharray="2 4" horizontal={false} />
                    <XAxis type="number" domain={[0, 1]} {...axis} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                    <YAxis type="category" dataKey="condition" {...axis} width={80} />
                    <RTooltip contentStyle={{ background: 'var(--mantine-color-body)', border: `1px solid ${grid}`, borderRadius: 6, fontSize: 12 }}
                      formatter={(v: number, n: string) => [`${(v * 100).toFixed(1)}%`, pretty(n)]} />
                    <Legend wrapperStyle={{ fontSize: 11 }} formatter={(v) => pretty(String(v))} />
                    {SHARE_KEYS.map((k, i) => (
                      <Bar key={k} dataKey={k} stackId="s" fill={colors[i % colors.length]} stroke="var(--mantine-color-body)" strokeWidth={1} isAnimationActive={false} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Card withBorder padding="sm">
                <Group justify="space-between">
                  <Text size="sm" fw={600}>Over time (mean across seeds)</Text>
                  <Select size="xs" w={160} value={seriesKey} onChange={(v) => v && setSeriesKey(v)} allowDeselect={false}
                    data={[{ value: 'alive', label: 'Agents alive' }, { value: 'tokens_mean', label: 'Mean tokens' },
                      { value: 'health_mean', label: 'Mean health' }, { value: 'trust_mean', label: 'Mean trust' },
                      { value: 'happiness_mean', label: 'Mean happiness' }]} />
                </Group>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={overlay} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                    <CartesianGrid stroke={grid} strokeDasharray="2 4" vertical={false} />
                    <XAxis dataKey="day" {...axis} />
                    <YAxis {...axis} />
                    <RTooltip contentStyle={{ background: 'var(--mantine-color-body)', border: `1px solid ${grid}`, borderRadius: 6, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {comparison.conditions.map((c: string, i: number) => (
                      <Line key={c} dataKey={c} stroke={colors[i % colors.length]} strokeWidth={2} dot={false} isAnimationActive={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </Card>
            </Grid.Col>
          </Grid>
          <Card withBorder padding="sm">
            <Text size="sm" fw={600} mb={4}>All measures (mean ± 95% CI; p = Welch t-test vs baseline)</Text>
            <ScrollArea>
              <Table fz="xs" striped withColumnBorders verticalSpacing={3}>
                <Table.Thead>
                  <Table.Tr><Table.Th>Measure</Table.Th>{comparison.conditions.map((c: string) => <Table.Th key={c}>{c}{c === comparison.baseline ? ' (baseline)' : ''}</Table.Th>)}</Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(comparison.metric_order ?? Object.keys(comparison.metrics)).map((metric: string) => [metric, comparison.metrics[metric]]).map(([metric, row]: [string, any]) => (
                    <Table.Tr key={metric}>
                      <Table.Td>{pretty(metric)}</Table.Td>
                      {comparison.conditions.map((c: string) => {
                        const e = row[c] ?? {};
                        const p = e.vs_baseline?.p;
                        return (
                          <Table.Td key={c}>
                            {fmt(e.mean)}{e.ci95 !== null && e.ci95 !== undefined ? ` ± ${fmt(e.ci95)}` : ''}
                            {p !== null && p !== undefined && (
                              <Text span size="xs" c={p < 0.05 ? 'teal' : 'dimmed'} fw={p < 0.05 ? 600 : undefined}> p={p.toPrecision(2)}</Text>
                            )}
                          </Table.Td>
                        );
                      })}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </Card>
        </>
      )}
      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb={4}>Runs</Text>
        <Table fz="xs" verticalSpacing={3}>
          <Table.Thead>
            <Table.Tr><Table.Th>Condition</Table.Th><Table.Th>Seed</Table.Th><Table.Th>Status</Table.Th><Table.Th>Survival</Table.Th><Table.Th>World</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(results?.runs ?? exp.worlds?.map((w: any) => ({ condition: w.condition, seed: w.seed, status: w.status, world_id: w.id })) ?? []).map((r: any, i: number) => (
              <Table.Tr key={i}>
                <Table.Td>{r.condition}</Table.Td>
                <Table.Td>{r.seed}</Table.Td>
                <Table.Td><Badge size="xs" variant="light" color={STATUS_COLOR[r.status] ?? 'gray'}>{pretty(r.status)}</Badge></Table.Td>
                <Table.Td>{r.summary ? fmt(r.summary.survival_rate, true) : '–'}</Table.Td>
                <Table.Td>
                  {r.world_id ? <Button size="compact-xs" variant="subtle" onClick={() => onOpenWorld(r.world_id)}>Open {r.world_id.slice(0, 6)}</Button> : r.error ?? '–'}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}

export function ExperimentsPage({ onOpenWorld }: Props) {
  const scheme = useComputedColorScheme('light');
  const colors = scheme === 'dark' ? SERIES_DARK : SERIES_LIGHT;
  const [list, setList] = useState<any[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.experiments().then((xs) => {
      setList(xs);
      setSelected((cur) => (cur && xs.some((x) => x.id === cur) ? cur : xs[0]?.id ?? null));
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(refresh, [refresh]);
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let stop = false;
    const load = () => api.experiment(selected).then((d) => { if (!stop) setDetail(d); }).catch((e) => setError(String(e)));
    load();
    const t = setInterval(() => {
      if (detail && !['pending', 'running'].includes(detail.status)) return;
      load();
      refresh();
    }, 1500);
    return () => { stop = true; clearInterval(t); };
  }, [selected, detail?.status, refresh]);

  return (
    <Grid gutter="sm">
      <Grid.Col span={{ base: 12, md: 3 }}>
        <Stack gap="xs">
          <Button onClick={() => setOpen(true)}>New experiment</Button>
          {error && <Alert color="red" withCloseButton onClose={() => setError(null)}>{error}</Alert>}
          {list.length === 0 && <Text size="sm" c="dimmed">No experiments yet. Compare conditions (e.g. scarcity vs abundance) across several random seeds.</Text>}
          {list.map((e) => (
            <Card key={e.id} withBorder padding="xs" onClick={() => setSelected(e.id)}
              style={{ cursor: 'pointer', borderColor: e.id === selected ? 'var(--mantine-primary-color-filled)' : undefined }}>
              <Group justify="space-between" wrap="nowrap">
                <Text size="sm" fw={600} lineClamp={1}>{e.name}</Text>
                <Badge size="xs" color={STATUS_COLOR[e.status] ?? 'gray'} variant="light">{pretty(e.status)}</Badge>
              </Group>
              <Text size="xs" c="dimmed">{e.spec.conditions.length} conditions · {e.spec.seeds.length} seeds · {e.spec.ticks} ticks</Text>
              {['running', 'pending'].includes(e.status) && <Progress value={(e.progress ?? 0) * 100} size="xs" mt={4} />}
            </Card>
          ))}
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 9 }}>
        {detail ? <ExperimentDetail exp={detail} onOpenWorld={onOpenWorld} onChanged={refresh} colors={colors} />
          : <Text c="dimmed" size="sm">Select or create an experiment.</Text>}
      </Grid.Col>
      <NewExperimentModal opened={open} onClose={() => setOpen(false)} onCreated={(id) => { setSelected(id); refresh(); }} />
    </Grid>
  );
}
