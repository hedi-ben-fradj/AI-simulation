// The chronicle: one storyline per simulated day, written when the day ends (by the
// world's LLM when it has one, otherwise by the built-in writer), with the day's
// highlights, every villager's status at nightfall, conversations and thoughts.
import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Alert, Badge, Box, Button, Card, Grid, Group, Paper, Progress, ScrollArea, SegmentedControl, SimpleGrid, Stack,
  Switch, Table, Text, Title, Tooltip, UnstyledButton,
} from '@mantine/core';
import { api } from '../api';
import type { AgentBrief, Chronicle, ChronicleDay, ChronicleHighlight } from '../types';
import { Avatar } from './Avatar';

const KIND_ICONS: Record<string, string> = {
  death: '☠️', birth: '👶', injury: '🩹', discovery: '🔎', theft: '🗡️', gift: '🎁', trade: '⚖️', refusal: '✋',
  creation: '🎨', belief: '✦', contemplation: '💭', group_talk: '👥', existential_talk: '✦', ignored: '📭',
  friendship: '🤝', distrust: '💔', impossible_plan: '🚫', trait_change: '🧬', shortage: '🍂', inequality: '💰',
  danger: '⚠️', first_meeting: '👋', isolation: '🕳️',
};
// Highlights worth a place in "key moments" across the whole chronicle.
const KEY_MOMENT_SCORE = 55;

// --- a tiny, safe markdown renderer: paragraphs, "- " bullets, **bold**, *italic*
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).filter(Boolean).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <b key={i}>{part.slice(2, -2)}</b>;
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <i key={i}>{part.slice(1, -1)}</i>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function StoryText({ text, size = 'sm' }: { text: string; size?: string }) {
  const blocks = text.split(/\n\s*\n/);
  return (
    <Stack gap={8}>
      {blocks.map((block, i) => {
        const lines = block.split('\n').filter((l) => l.trim());
        const bullets = lines.filter((l) => /^\s*[-•*]\s+/.test(l));
        if (bullets.length && bullets.length >= lines.length - 1) {
          const head = lines.length > bullets.length ? lines[0] : null;
          return (
            <div key={i}>
              {head && <Text size={size} fw={600}>{inline(head)}</Text>}
              <Stack gap={2} mt={2}>
                {bullets.map((l, j) => (
                  <Text key={j} size={size} pl="sm">• {inline(l.replace(/^\s*[-•*]\s+/, ''))}</Text>
                ))}
              </Stack>
            </div>
          );
        }
        return <Text key={i} size={size} style={{ lineHeight: 1.6 }}>{inline(lines.join(' '))}</Text>;
      })}
    </Stack>
  );
}

function DayBadges({ day }: { day: ChronicleDay }) {
  const s = day.stats ?? {};
  const items: [string, number | undefined, string][] = [
    ['💬', s.messages, 'messages'], ['☠️', s.deaths, 'deaths'], ['🗡️', s.thefts, 'thefts'], ['🎁', s.gifts, 'gifts'],
    ['✦', (s.beliefs ?? 0) + (s.existential_messages ?? 0), 'about existence'],
  ];
  return (
    <Group gap={6}>
      {items.filter(([, n]) => n).map(([icon, n, label]) => (
        <Tooltip key={label} label={label}><Text size="xs" c="dimmed">{icon} {n}</Text></Tooltip>
      ))}
    </Group>
  );
}

function Highlights({ items }: { items: ChronicleHighlight[] }) {
  if (!items.length) return <Text size="sm" c="dimmed">Nothing out of the ordinary.</Text>;
  return (
    <Stack gap={4}>
      {items.map((h, i) => (
        <Text key={i} size="sm">
          <span style={{ display: 'inline-block', width: 22 }}>{KIND_ICONS[h.kind] ?? '•'}</span>
          {h.text}
          {h.quote && <Text span c="dimmed" fs="italic"> “{h.quote}”</Text>}
        </Text>
      ))}
    </Stack>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <Text fw={700} size="sm" mb={6}>{title}</Text>
      {children}
    </div>
  );
}

interface DayViewProps {
  worldId: string;
  day: ChronicleDay;
  llm: boolean;
  version: number;
  sprites: Record<string, string>;
  onOpenConversation: (participants: string[]) => void;
  onSelectAgent: (id: string) => void;
  onRewritten: () => void;
}

function DayView({ worldId, day, llm, version, sprites, onOpenConversation, onSelectAgent, onRewritten }: DayViewProps) {
  const [detail, setDetail] = useState<ChronicleDay | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setError(null);
    api.chronicleDay(worldId, day.day).then(setDetail).catch((e) => setError(String(e)));
  }, [worldId, day.day, day.headline, day.narrator, version, day.in_progress ? day.to_tick : 0]);

  const d = detail?.day === day.day ? detail : null;
  const digest = d?.digest;
  const rewrite = async () => {
    setBusy(true);
    setError(null);
    try {
      setDetail(await api.narrateDay(worldId, day.day));
      onRewritten();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const shown = d ?? day;
  return (
    <Stack gap="md">
      <div>
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <div>
            <Text size="xs" c="dimmed" fw={600}>DAY {shown.day}{shown.in_progress ? ' · SO FAR' : ''}</Text>
            <Title order={3}>{shown.headline}</Title>
          </div>
          <Group gap={6} wrap="nowrap">
            <Badge variant="light" color={shown.narrator === 'llm' ? 'violet' : 'gray'}>
              {shown.narrator === 'llm' ? `written by ${shown.model ?? 'the LLM'}` : 'built-in writer'}
            </Badge>
            {llm && !shown.in_progress && (
              <Button size="compact-xs" variant="light" loading={busy} onClick={rewrite}>
                {shown.narrator === 'llm' ? 'Rewrite' : 'Write with the LLM'}
              </Button>
            )}
          </Group>
        </Group>
        {error && <Alert color="red" mt="xs" p="xs">{error}</Alert>}
      </div>

      <Paper withBorder p="md" radius="md">
        <StoryText text={shown.story} />
      </Paper>

      {shown.notable?.length > 0 && (
        <Section title="Notable">
          <Stack gap={2}>{shown.notable.map((n, i) => <Text key={i} size="sm">• {n}</Text>)}</Stack>
        </Section>
      )}

      <Section title="Highlights — unusual and interesting">
        <Highlights items={(digest?.highlights ?? shown.highlights ?? []).slice(0, 12)} />
      </Section>

      {digest && digest.agents.length > 0 && (
        <Section title={shown.in_progress ? 'Villagers right now' : 'Villagers at nightfall'}>
          <ScrollArea type="auto">
            <Table fz="xs" verticalSpacing={4} miw={620}>
              <Table.Thead>
                <Table.Tr><Table.Th>Villager</Table.Th><Table.Th w={120}>Health</Table.Th><Table.Th>Hunger</Table.Th>
                  <Table.Th>Tokens</Table.Th><Table.Th>Mood</Table.Th><Table.Th>Spent the day</Table.Th><Table.Th>Msgs</Table.Th></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {digest.agents.map((a) => (
                  <Table.Tr key={a.id} style={{ opacity: a.alive ? 1 : 0.55, cursor: 'pointer' }} onClick={() => onSelectAgent(a.id)}>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <Avatar sprite={a.sprite || sprites[a.id]} size={22} dead={!a.alive} />
                        <Text size="xs" fw={600}>{a.name}</Text>
                        {a.controller === 'llm' && <Badge size="xs" color="violet" variant="light">LLM</Badge>}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      {a.alive ? (
                        <Tooltip label={`${a.health.toFixed(0)}/100${a.change?.health ? ` (${a.change.health > 0 ? '+' : ''}${a.change.health} today)` : ''}`}>
                          <Progress value={a.health} size="sm" color={a.health > 50 ? 'teal' : a.health > 25 ? 'yellow' : 'red'} />
                        </Tooltip>
                      ) : '☠️ dead'}
                    </Table.Td>
                    <Table.Td>{a.alive ? a.hunger.toFixed(0) : ''}</Table.Td>
                    <Table.Td>
                      {a.alive ? a.tokens.toFixed(0) : ''}
                      {a.alive && a.change?.tokens ? <Text span size="xs" c={a.change.tokens > 0 ? 'teal' : 'red'}> {a.change.tokens > 0 ? '+' : ''}{a.change.tokens}</Text> : null}
                    </Table.Td>
                    <Table.Td>{a.mood}</Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed" lineClamp={1}>
                        {Object.entries(a.hours ?? {}).sort((x, y) => y[1] - x[1]).slice(0, 3).map(([k, h]) => `${k.replace(/_/g, ' ')} ${h}h`).join(' · ') || '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>{a.messages_sent}↑ {a.messages_received}↓</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Section>
      )}

      {digest && digest.conversations.length > 0 && (
        <Section title="Conversations">
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
            {digest.conversations.map((c, i) => (
              <Card key={i} withBorder padding="sm">
                <Group justify="space-between" mb={4} wrap="nowrap">
                  <Group gap={6} wrap="nowrap">
                    {c.participants.slice(0, 4).map((p) => <Avatar key={p} sprite={sprites[p]} size={20} />)}
                    <Text size="sm" fw={600} truncate>{c.names.join(c.group ? ', ' : ' & ')}</Text>
                  </Group>
                  <Button size="compact-xs" variant="subtle" onClick={() => onOpenConversation(c.participants)}>Open</Button>
                </Group>
                <Stack gap={2}>
                  {c.excerpt.slice(0, 4).map((x, j) => (
                    <Text key={j} size="xs"><b>{x.from}</b>{c.group ? ` → ${x.to}` : ''}: {x.text}</Text>
                  ))}
                  {c.message_count > 4 && <Text size="xs" c="dimmed">… {c.message_count - 4} more</Text>}
                </Stack>
              </Card>
            ))}
          </SimpleGrid>
        </Section>
      )}

      {digest && digest.thoughts.length > 0 && (
        <Section title="Thoughts">
          <Stack gap={4}>
            {digest.thoughts.slice(0, 14).map((t, i) => (
              <Group key={i} gap={6} wrap="nowrap" align="flex-start">
                <Avatar sprite={sprites[t.agent_id]} size={18} />
                <Text size="xs"><b>{t.agent}</b> <Text span c="dimmed" fs="italic">“{t.text}”</Text>
                  {t.existential && <Text span c="violet"> ✦</Text>}</Text>
              </Group>
            ))}
          </Stack>
        </Section>
      )}

      {digest && (
        <Section title="In numbers">
          <Group gap="lg">
            {([
              ['messages', digest.stats.messages], ['conversations', digest.stats.conversations],
              ['time together', digest.stats.socialising], ['gifts', digest.stats.gifts], ['trades', digest.stats.trades],
              ['refusals', digest.stats.refusals], ['thefts', digest.stats.thefts], ['deaths', digest.stats.deaths],
              ['plans refused by the world', digest.stats.rejected_plans], ['LLM decisions', digest.stats.llm_decisions],
              ['food left', digest.economy.food_stock_end], ['mean trust', digest.economy.trust_mean_end?.toFixed?.(2)],
            ] as [string, number | string | undefined][]).filter(([, v]) => v !== undefined && v !== null).map(([label, v]) => (
              <div key={label}><Text size="xs" c="dimmed">{label}</Text><Text fw={700}>{v}</Text></div>
            ))}
          </Group>
        </Section>
      )}
    </Stack>
  );
}

interface Props {
  worldId: string;
  worldName: string;
  tick: number;
  version: number;
  agents: AgentBrief[];
  onOpenConversation: (participants: string[]) => void;
  onSelectAgent: (id: string) => void;
}

export function ChroniclePage({ worldId, worldName, tick, version, agents, onOpenConversation, onSelectAgent }: Props) {
  const [data, setData] = useState<Chronicle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [mode, setMode] = useState<'days' | 'story'>('days');
  const [newestFirst, setNewestFirst] = useState(false);
  const [reload, setReload] = useState(0);
  const sprites = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a.sprite ?? 'human-worker-red'])), [agents]);

  useEffect(() => {
    const t = setTimeout(() => {
      api.chronicle(worldId).then((c) => { setData(c); setError(null); }).catch((e) => setError(String(e)));
    }, 200);
    return () => clearTimeout(t);
  }, [worldId, version, reload, Math.floor(tick / 6)]);

  const days = data?.days ?? [];
  const all: ChronicleDay[] = useMemo(() => [...days, ...(data?.today ? [data.today] : [])], [data]);
  const ordered = newestFirst ? [...all].reverse() : all;
  const current = all.find((d) => d.day === selected) ?? all[all.length - 1] ?? null;
  const keyMoments = useMemo(() => days.flatMap((d) => d.highlights
    .filter((h) => h.score >= KEY_MOMENT_SCORE).map((h) => ({ day: d.day, h }))), [days]);
  const totals = useMemo(() => days.reduce((acc, d) => {
    for (const k of ['messages', 'deaths', 'thefts', 'gifts', 'beliefs']) acc[k] = (acc[k] ?? 0) + (d.stats?.[k] ?? 0);
    return acc;
  }, {} as Record<string, number>), [days]);
  const alive = agents.filter((a) => a.alive).length;

  if (error) return <Alert color="red">{error}</Alert>;
  if (!data) return <Text c="dimmed">Loading the chronicle…</Text>;

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={3}>📖 The chronicle of {worldName}</Title>
          <Text size="sm" c="dimmed">
            A storyline for every day, written when the day ends
            {data.narrator.llm ? ` by ${data.narrator.model}` : ' by the built-in writer (choose an LLM on the setup page for richer stories)'}.
          </Text>
        </div>
        <Group gap="xs">
          <SegmentedControl size="xs" value={mode} onChange={(v) => setMode(v as typeof mode)}
            data={[{ value: 'days', label: 'Day by day' }, { value: 'story', label: 'Whole story' }]} />
          <Switch size="xs" label="Newest first" checked={newestFirst} onChange={(e) => setNewestFirst(e.currentTarget.checked)} />
          <Button size="xs" variant="default" component="a" href={api.chronicleMarkdownUrl(worldId)} download>Download (.md)</Button>
        </Group>
      </Group>

      <Card withBorder padding="sm">
        <Grid gutter="md">
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Text fw={700} size="sm" mb={6}>The story so far</Text>
            <SimpleGrid cols={3} spacing="xs">
              {([['days', days.length], ['alive now', `${alive}/${agents.length}`], ['messages', totals.messages ?? 0],
                ['deaths', totals.deaths ?? 0], ['thefts', totals.thefts ?? 0], ['beliefs', totals.beliefs ?? 0]] as [string, string | number][]).map(([l, v]) => (
                <div key={l}><Text size="xs" c="dimmed">{l}</Text><Text fw={700}>{v}</Text></div>
              ))}
            </SimpleGrid>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 8 }}>
            <Text fw={700} size="sm" mb={6}>Key moments</Text>
            {keyMoments.length === 0 ? <Text size="sm" c="dimmed">No dramatic events yet.</Text> : (
              <ScrollArea.Autosize mah={120} type="auto">
                <Stack gap={2}>
                  {keyMoments.map(({ day, h }, i) => (
                    <UnstyledButton key={i} onClick={() => { setSelected(day); setMode('days'); }}>
                      <Text size="xs"><Text span c="dimmed" fw={600} w={52} display="inline-block">Day {day}</Text>
                        {KIND_ICONS[h.kind] ?? '•'} {h.text}</Text>
                    </UnstyledButton>
                  ))}
                </Stack>
              </ScrollArea.Autosize>
            )}
          </Grid.Col>
        </Grid>
      </Card>

      {all.length === 0 && (
        <Text c="dimmed">The first chapter is written at the end of day 1 ({data.ticks_per_day} ticks). Start the simulation and come back later.</Text>
      )}

      {mode === 'days' && current && (
        <Grid gutter="md">
          <Grid.Col span={{ base: 12, md: 4 }}>
            <ScrollArea h="min(72vh, 900px)" type="auto" offsetScrollbars>
              <Stack gap={6}>
                {ordered.map((d) => (
                  <UnstyledButton key={d.day} onClick={() => setSelected(d.day)} p={8}
                    style={{ borderRadius: 8, border: '1px solid var(--mantine-color-default-border)',
                      background: d.day === current.day ? 'var(--mantine-color-default-hover)' : undefined }}>
                    <Group justify="space-between" wrap="nowrap" mb={2}>
                      <Text size="xs" fw={700} c="dimmed">DAY {d.day}{d.in_progress ? ' · IN PROGRESS' : ''}</Text>
                      {d.narrator === 'llm' && <Text size="xs" c="violet">✍</Text>}
                    </Group>
                    <Text size="sm" fw={600} lineClamp={2}>{d.headline}</Text>
                    <DayBadges day={d} />
                  </UnstyledButton>
                ))}
              </Stack>
            </ScrollArea>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 8 }}>
            <DayView worldId={worldId} day={current} llm={data.narrator.llm} version={version} sprites={sprites}
              onOpenConversation={onOpenConversation} onSelectAgent={onSelectAgent} onRewritten={() => setReload((n) => n + 1)} />
          </Grid.Col>
        </Grid>
      )}

      {mode === 'story' && (
        <Box maw={820} mx="auto" w="100%">
          <Stack gap="xl">
            {ordered.map((d) => (
              <div key={d.day}>
                <Text size="xs" c="dimmed" fw={700}>DAY {d.day}{d.in_progress ? ' · SO FAR' : ''}</Text>
                <Title order={4} mb={6}>{d.headline}</Title>
                <StoryText text={d.story} />
                {d.notable?.length > 0 && (
                  <Stack gap={0} mt={6}>{d.notable.map((n, i) => <Text key={i} size="sm" c="dimmed">• {n}</Text>)}</Stack>
                )}
                <Button size="compact-xs" variant="subtle" mt={4} onClick={() => { setSelected(d.day); setMode('days'); }}>
                  Details of day {d.day} →
                </Button>
              </div>
            ))}
          </Stack>
        </Box>
      )}
    </Stack>
  );
}
