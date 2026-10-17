import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion, ActionIcon, Alert, Badge, Box, Button, Card, Grid, Group, NumberInput, ScrollArea, SegmentedControl, Select,
  SimpleGrid, Slider, Stack, Switch, Text, TextInput, Title, Tooltip, useComputedColorScheme,
} from '@mantine/core';
import { api } from '../api';
import type { WorldSummary, WorldView } from '../types';
import { trustColor } from '../theme';

interface Props {
  worlds: WorldSummary[];
  onCreated: (w: WorldView) => void;
  onOpenWorld: (id: string) => void;
}

interface Settings {
  name: string;
  population: number;
  resource_level: string;
  personality_mode: 'identical' | 'random';
  personality_deviation: number;
  personality_distribution: 'normal' | 'uniform';
  trait_means: Record<string, number>;
  days: number | null;
  seed: number;
  world_size: string;
  communication_cost: string;
  trust_prior: string;
  allow_theft: boolean;
  hazards: string;
  replace_dead: boolean;
  existential_goal: boolean;
  provider: 'none' | 'mock' | 'anthropic';
  llm_agents: number | null;
  model: string | null;
  effort: string | null;
  max_world_spend: number | null;
}

const DEFAULTS: Settings = {
  name: '', population: 5, resource_level: 'normal', personality_mode: 'random', personality_deviation: 0.15,
  personality_distribution: 'normal', trait_means: {}, days: null, seed: 42, world_size: 'auto',
  communication_cost: 'normal', trust_prior: 'neutral', allow_theft: true, hazards: 'low', replace_dead: false,
  existential_goal: true, provider: 'none', llm_agents: null, model: null, effort: null, max_world_spend: 2,
};

const LEVELS = ['very_scarce', 'scarce', 'almost_scarce', 'normal', 'almost_abundant', 'abundant', 'very_abundant'];
const LEVEL_LABELS = ['Very scarce', 'Scarce', 'Almost scarce', 'Normal', 'Almost abundant', 'Abundant', 'Very abundant'];
const STORE_KEY = 'aisim.setup';

const pretty = (s: string) => s.replace(/_/g, ' ');

function loadStored(): Settings {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card withBorder padding="md">
      <Text fw={700} mb={2}>{title}</Text>
      {description && <Text size="xs" c="dimmed" mb="sm">{description}</Text>}
      <Stack gap="sm">{children}</Stack>
    </Card>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Tooltip label={hint} disabled={!hint} multiline w={240}>
      <div>
        <Text size="xs" c="dimmed">{label}</Text>
        <Text fw={700}>{value}</Text>
      </div>
    </Tooltip>
  );
}

export function SetupPage({ worlds, onCreated, onOpenWorld }: Props) {
  const scheme = useComputedColorScheme('light');
  const [s, setS] = useState<Settings>(loadStored);
  const [options, setOptions] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setS((prev) => ({ ...prev, [key]: value }));

  useEffect(() => {
    api.setupOptions().then(setOptions).catch((e) => setError(String(e)));
  }, []);

  const payload = useMemo(() => ({ ...s, name: s.name.trim() || null }), [s]);

  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(s));
    } catch {
      /* storage unavailable */
    }
    const id = ++seq.current;
    const t = setTimeout(() => {
      api.setupPreview({ ...payload, start: false })
        .then((p) => { if (id === seq.current) { setPreview(p); setError(null); } })
        .catch((e) => { if (id === seq.current) setError(String(e)); });
    }, 250);
    return () => clearTimeout(t);
  }, [payload]);

  const create = async (start: boolean) => {
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.setupWorld({ ...payload, start }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const levelIndex = Math.max(0, LEVELS.indexOf(s.resource_level));
  const levelInfo = options?.resource_levels?.[levelIndex];
  const econ = preview?.economy;
  const traits: string[] = options?.traits ?? [];
  const deviationPct = Math.round(s.personality_deviation * 100);

  return (
    <Grid gutter="md">
      <Grid.Col span={{ base: 12, lg: 7 }}>
        <Stack gap="md">
          <div>
            <Title order={2}>Set up a simulation</Title>
            <Text c="dimmed" size="sm">Choose the community, how plentiful the world is, and how agents differ. Everything can be inspected afterwards.</Text>
          </div>

          <Section title="Community" description="Small communities (2–6 agents) are easiest to follow; larger ones show more social structure.">
            <Group grow align="flex-end">
              <TextInput label="Name" placeholder="e.g. Two strangers" value={s.name} onChange={(e) => set('name', e.currentTarget.value)} />
              <NumberInput label="Duration (days)" placeholder="Unlimited" min={1} max={365} value={s.days ?? ''}
                onChange={(v) => set('days', v === '' ? null : Number(v))} />
            </Group>
            <div>
              <Group justify="space-between">
                <Text size="sm" fw={500}>Number of agents</Text>
                <NumberInput size="xs" w={80} min={2} max={50} value={s.population}
                  onChange={(v) => set('population', Math.max(2, Math.min(50, Number(v) || 2)))} aria-label="Number of agents" />
              </Group>
              <Slider min={2} max={20} step={1} value={Math.min(20, s.population)} onChange={(v) => set('population', v)}
                marks={[2, 5, 10, 15, 20].map((v) => ({ value: v, label: String(v) }))} mb="md" thumbLabel="Number of agents slider" />
            </div>
            <Group grow align="flex-end">
              <Select label="World size" value={s.world_size} onChange={(v) => v && set('world_size', v)} allowDeselect={false}
                data={[{ value: 'auto', label: 'Auto (by population)' }, { value: 'compact', label: 'Compact' },
                  { value: 'normal', label: 'Normal' }, { value: 'large', label: 'Large' }]} />
              <NumberInput label="Random seed" description="Same seed + settings = same world" min={0} value={s.seed}
                onChange={(v) => set('seed', Number(v) || 0)}
                rightSection={<ActionIcon variant="subtle" aria-label="Random seed" onClick={() => set('seed', Math.floor(Math.random() * 100000))}>⚄</ActionIcon>} />
            </Group>
          </Section>

          <Section title="Resources" description="Sets food supply (relative to what the population needs), meal prices, wages, jobs and starting money.">
            <Text size="lg" fw={700} ta="center">{LEVEL_LABELS[levelIndex]}</Text>
            <Slider min={0} max={6} step={1} value={levelIndex} onChange={(v) => set('resource_level', LEVELS[v])}
              label={(v) => LEVEL_LABELS[v]} marks={LEVEL_LABELS.map((_, i) => ({ value: i }))}
              thumbLabel="Resource abundance" />
            <Group justify="space-between" mt={-6}>
              {['Very scarce', 'Normal', 'Very abundant'].map((l) => <Text key={l} size="xs" c="dimmed">{l}</Text>)}
            </Group>
            {levelInfo && (
              <Text size="xs" c="dimmed">
                Food supply {Math.round(levelInfo.supply_ratio * 100)}% of needs · meal {levelInfo.food_price} tokens ·
                wage {levelInfo.wage}/hour · start with {levelInfo.starting_tokens} tokens · jobs for {Math.round(levelInfo.job_ratio * 100)}% of agents
              </Text>
            )}
          </Section>

          <Section title="Personality" description="Sixteen traits (artistic, spirituality, generosity…) on a 0–100% scale. They shape choices and drift slowly with experience.">
            <SegmentedControl value={s.personality_mode} onChange={(v) => set('personality_mode', v as Settings['personality_mode'])}
              data={[{ value: 'identical', label: 'Identical (everyone 50%)' }, { value: 'random', label: 'Randomised' }]} />
            {s.personality_mode === 'identical' ? (
              <Text size="sm" c="dimmed">All agents start with exactly the same traits{Object.keys(s.trait_means).length ? ' (custom averages below)' : ' — 50% each'}. Differences can only come from experience.</Text>
            ) : (
              <>
                <div>
                  <Text size="sm" fw={500}>Deviation from 50%: ±{deviationPct}%</Text>
                  <Slider min={0} max={50} step={1} value={deviationPct} onChange={(v) => set('personality_deviation', v / 100)}
                    label={(v) => `±${v}%`} marks={[0, 10, 20, 30, 40, 50].map((v) => ({ value: v, label: `${v}%` }))} mb="md"
                    thumbLabel="Personality deviation" />
                </div>
                <SegmentedControl size="xs" value={s.personality_distribution}
                  onChange={(v) => set('personality_distribution', v as Settings['personality_distribution'])}
                  data={[{ value: 'normal', label: 'Bell curve (± is one standard deviation)' }, { value: 'uniform', label: 'Uniform (anywhere within ±)' }]} />
                <Text size="xs" c="dimmed">
                  {s.personality_distribution === 'normal'
                    ? `About two thirds of trait values fall between ${50 - deviationPct}% and ${50 + deviationPct}%; a few go further (clipped to 0–100%).`
                    : `Every trait value lies between ${Math.max(0, 50 - deviationPct)}% and ${Math.min(100, 50 + deviationPct)}%.`}
                </Text>
              </>
            )}
            <Accordion variant="contained">
              <Accordion.Item value="means">
                <Accordion.Control>Custom trait averages {Object.keys(s.trait_means).length > 0 && <Badge size="xs" ml="xs">{Object.keys(s.trait_means).length} changed</Badge>}</Accordion.Control>
                <Accordion.Panel>
                  <Group justify="flex-end" mb="xs">
                    <Button size="compact-xs" variant="subtle" onClick={() => set('trait_means', {})}>Reset all to 50%</Button>
                  </Group>
                  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
                    {traits.map((t) => {
                      const v = Math.round((s.trait_means[t] ?? 0.5) * 100);
                      return (
                        <div key={t}>
                          <Text size="xs">{pretty(t)}: {v}%</Text>
                          <Slider size="sm" min={0} max={100} value={v} label={null} thumbLabel={`${t} average`}
                            onChange={(nv) => {
                              const next = { ...s.trait_means };
                              if (nv === 50) delete next[t];
                              else next[t] = nv / 100;
                              set('trait_means', next);
                            }} />
                        </div>
                      );
                    })}
                  </SimpleGrid>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>
          </Section>

          <Section title="Society and environment">
            <Group grow>
              <Select label="Cost of sending messages" value={s.communication_cost} onChange={(v) => v && set('communication_cost', v)} allowDeselect={false}
                data={[{ value: 'free', label: 'Free' }, { value: 'cheap', label: 'Cheap' }, { value: 'normal', label: 'Normal' }, { value: 'expensive', label: 'Expensive' }]} />
              <Select label="Trust towards strangers" value={s.trust_prior} onChange={(v) => v && set('trust_prior', v)} allowDeselect={false}
                data={[{ value: 'trusting', label: 'Trusting' }, { value: 'neutral', label: 'Neutral' }, { value: 'suspicious', label: 'Suspicious' }]} />
              <Select label="Environmental hazards" value={s.hazards} onChange={(v) => v && set('hazards', v)} allowDeselect={false}
                data={[{ value: 'none', label: 'None' }, { value: 'low', label: 'Low (only when exploring)' }, { value: 'high', label: 'High' }]} />
            </Group>
            <Group>
              <Switch label="Theft is possible" checked={s.allow_theft} onChange={(e) => set('allow_theft', e.currentTarget.checked)} />
              <Switch label="Replace agents who die" checked={s.replace_dead} onChange={(e) => set('replace_dead', e.currentTarget.checked)} />
              <Switch label="Existential goal (why do I exist?)" checked={s.existential_goal} onChange={(e) => set('existential_goal', e.currentTarget.checked)} />
            </Group>
          </Section>

          <Section title="Agent minds" description="Rule-based agents are free and reproducible. Claude agents reason in language; calls happen only on the server and are capped by the spend limit.">
            <SegmentedControl value={s.provider} onChange={(v) => set('provider', v as Settings['provider'])}
              data={[{ value: 'none', label: 'Rule-based' }, { value: 'mock', label: 'Mock LLM (offline test)' }, { value: 'anthropic', label: 'Claude' }]} />
            {s.provider !== 'none' && (
              <Group grow align="flex-end">
                <NumberInput label="How many agents use the LLM" placeholder={`All ${s.population}`} min={0} max={s.population}
                  value={s.llm_agents ?? ''} onChange={(v) => set('llm_agents', v === '' ? null : Number(v))} />
                {s.provider === 'anthropic' && (
                  <>
                    <Select label="Model" placeholder="claude-opus-5-5" value={s.model} onChange={(v) => set('model', v)} clearable
                      data={options?.models ?? []} />
                    <Select label="Effort" placeholder="low" value={s.effort} onChange={(v) => set('effort', v)} clearable
                      data={['low', 'medium', 'high']} />
                    <NumberInput label="Spend cap (USD)" min={0} decimalScale={2} value={s.max_world_spend ?? ''}
                      onChange={(v) => set('max_world_spend', v === '' ? null : Number(v))} placeholder="no cap" />
                  </>
                )}
              </Group>
            )}
            {s.provider === 'anthropic' && options && !options.anthropic_key_configured && (
              <Alert color="yellow">The server has no ANTHROPIC_API_KEY, so Claude agents will fall back to rule-based decisions.</Alert>
            )}
          </Section>
        </Stack>
      </Grid.Col>

      <Grid.Col span={{ base: 12, lg: 5 }}>
        <Box style={{ position: 'sticky', top: 70 }}>
          <Stack gap="md">
            <Card withBorder padding="md">
              <Text fw={700} mb="xs">What this world will be like</Text>
              {econ ? (
                <SimpleGrid cols={2} spacing="sm">
                  <Stat label="Agents" value={`${econ.population}${preview.llm_agents ? ` (${preview.llm_agents} LLM)` : ''}`} />
                  <Stat label="Food supply vs need" value={`${Math.round(econ.food_supply_vs_need * 100)}%`}
                    hint={`${econ.food_supply_per_day} meals restocked per day; each agent needs about ${econ.meals_needed_per_agent_per_day}.`} />
                  <Stat label="Meal price" value={`${econ.meal_price} tokens`} />
                  <Stat label="Wage" value={`${econ.wage_per_tick} tokens/hour`} />
                  <Stat label="Work needed for food" value={`${econ.work_hours_for_food_per_day} h/day`} hint="Hours of work per day to pay for enough meals." />
                  <Stat label="Starting savings" value={`${econ.starting_tokens} tokens`} hint={`Enough for about ${econ.days_of_food_from_savings} day(s) of food.`} />
                  <Stat label="Jobs" value={`${econ.work_slots} slot(s)`} hint="How many agents can work at the same time." />
                  <Stat label="Duration" value={s.days ? `${s.days} day(s)` : 'Unlimited'} />
                </SimpleGrid>
              ) : <Text size="sm" c="dimmed">Calculating…</Text>}
              {preview?.warnings?.map((w: string) => <Alert key={w} color="orange" mt="sm" p="xs">{w}</Alert>)}
              {error && <Alert color="red" mt="sm">{error}</Alert>}
              <Group grow mt="md">
                <Button variant="default" loading={busy} onClick={() => create(false)}>Create paused</Button>
                <Button loading={busy} onClick={() => create(true)}>Start simulation</Button>
              </Group>
            </Card>

            {preview?.agents && (
              <Card withBorder padding="md">
                <Text fw={700}>Starting personalities</Text>
                <Text size="xs" c="dimmed" mb="xs">Each square is a trait: grey = 50%, red = lower, blue = higher. Hover for values.</Text>
                <ScrollArea.Autosize mah={320}>
                  <Stack gap={4}>
                    {preview.agents.map((a: any) => (
                      <Group key={a.name} gap={6} wrap="nowrap">
                        <Text size="xs" w={56} fw={600} style={{ flexShrink: 0 }}>{a.name}</Text>
                        <Group gap={2} wrap="nowrap">
                          {traits.map((t) => (
                            <Tooltip key={t} label={`${pretty(t)}: ${Math.round(a.personality[t] * 100)}%`}>
                              <div style={{ width: 14, height: 14, borderRadius: 2, background: trustColor(a.personality[t], scheme),
                                border: '1px solid var(--mantine-color-default-border)' }} />
                            </Tooltip>
                          ))}
                        </Group>
                      </Group>
                    ))}
                  </Stack>
                </ScrollArea.Autosize>
              </Card>
            )}

            {worlds.length > 0 && (
              <Card withBorder padding="md">
                <Text fw={700} mb="xs">Or continue a saved world</Text>
                <Stack gap={4}>
                  {worlds.filter((w) => !w.experiment_id).slice(0, 6).map((w) => (
                    <Group key={w.id} justify="space-between" wrap="nowrap">
                      <Text size="sm" lineClamp={1}>{w.name} <Text span size="xs" c="dimmed">· tick {w.tick} · {w.status}</Text></Text>
                      <Button size="compact-xs" variant="light" onClick={() => onOpenWorld(w.id)}>Open</Button>
                    </Group>
                  ))}
                </Stack>
              </Card>
            )}
          </Stack>
        </Box>
      </Grid.Col>
    </Grid>
  );
}
