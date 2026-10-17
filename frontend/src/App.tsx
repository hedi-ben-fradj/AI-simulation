import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon, Alert, AppShell, Badge, Box, Button, Card, Grid, Group, Notification, SegmentedControl, Select, Stack, Table, Tabs, Text,
  Title, Tooltip, useMantineColorScheme,
} from '@mantine/core';
import { api } from './api';
import { useWorldStream } from './hooks/useWorldStream';
import { WorldCanvas, type ThoughtMode } from './components/WorldCanvas';
import { WorldControls } from './components/WorldControls';
import { CreateWorldModal } from './components/CreateWorldModal';
import { AgentInspector } from './components/AgentInspector';
import { EventFeed } from './components/EventFeed';
import { Analytics } from './components/Analytics';
import { LLMPanel } from './components/LLMPanel';
import { SocietyPanel } from './components/SocietyPanel';
import { MindPanel } from './components/MindPanel';
import { ExperimentsPage } from './components/ExperimentsPage';
import type { WorldSummary } from './types';
import { LOCATION_COLORS, MOOD_COLORS, hex } from './theme';

const WORLD_KEY = 'aisim.world';

function readStoredWorld(): string | null {
  const fromHash = window.location.hash.replace(/^#/, '');
  if (fromHash && fromHash !== 'experiments') return fromHash;
  try {
    return localStorage.getItem(WORLD_KEY);
  } catch {
    return null;
  }
}

function Legend() {
  return (
    <Group gap="md" wrap="wrap">
      {Object.entries(LOCATION_COLORS).filter(([k]) => k !== 'wild').map(([k, c]) => (
        <Group key={k} gap={4}><Box w={10} h={10} style={{ borderRadius: 5, background: hex(c) }} /><Text size="xs">{k}</Text></Group>
      ))}
      <Text size="xs" c="dimmed">|</Text>
      {['content', 'calm', 'contemplative', 'lonely', 'stressed', 'starving', 'exhausted'].map((m) => (
        <Group key={m} gap={4}><Box w={10} h={10} style={{ borderRadius: 5, background: hex(MOOD_COLORS[m]) }} /><Text size="xs">{m}</Text></Group>
      ))}
      <Text size="xs" c="dimmed">white ring = LLM agent · violet halo = existential question salient</Text>
    </Group>
  );
}

export default function App() {
  const [worlds, setWorlds] = useState<WorldSummary[]>([]);
  const [worldId, setWorldId] = useState<string | null>(readStoredWorld);
  const [selected, setSelected] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<string | null>('world');
  const [view, setView] = useState<'worlds' | 'experiments'>(() => (window.location.hash === '#experiments' ? 'experiments' : 'worlds'));
  const [thoughts, setThoughts] = useState<ThoughtMode>('all');
  const stream = useWorldStream(worldId);
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();

  const loadWorlds = useCallback(() => {
    api.worlds().then((ws) => {
      setWorlds(ws);
      setWorldId((cur) => (cur && ws.some((w) => w.id === cur) ? cur : ws[0]?.id ?? null));
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(loadWorlds, [loadWorlds]);
  useEffect(() => {
    setSelected(null);
    if (!worldId || view !== 'worlds') return;
    window.history.replaceState(null, '', `#${worldId}`);
    try {
      localStorage.setItem(WORLD_KEY, worldId);
    } catch {
      /* ignore */
    }
  }, [worldId, view]);
  useEffect(() => {
    if (view === 'experiments') window.history.replaceState(null, '', '#experiments');
  }, [view]);

  const world = stream.world;
  const agentNames = useMemo(() => Object.fromEntries((world?.agents ?? []).map((a) => [a.id, a.name])), [world?.agents]);
  const tickIntervalMs = world && world.speed > 0 ? 1000 / world.speed : 250;

  const deleteWorld = async () => {
    if (!worldId || !window.confirm('Delete this world and all of its history? This cannot be undone.')) return;
    try {
      await api.deleteWorld(worldId);
      setWorldId(null);
      loadWorlds();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <AppShell header={{ height: { base: 96, md: 56 } }} padding="sm">
      <AppShell.Header px="sm">
        <Group h="100%" justify="space-between" wrap="wrap" gap="xs" py={6}>
          <Group gap="xs" wrap="nowrap">
            <Title order={4} style={{ whiteSpace: 'nowrap' }}>Agent Civilization</Title>
            <SegmentedControl size="xs" value={view} onChange={(v) => setView(v as 'worlds' | 'experiments')}
              data={[{ value: 'worlds', label: 'Worlds' }, { value: 'experiments', label: 'Experiments' }]} />
            {view === 'worlds' && (<>
            <Select
              size="xs"
              placeholder="Select a world"
              data={worlds.map((w) => ({ value: w.id, label: w.experiment_id ? `▸ ${w.name}` : `${w.name} · ${w.id.slice(0, 6)}` }))}
              value={worldId}
              onChange={setWorldId}
              onDropdownOpen={loadWorlds}
              w={220}
              aria-label="World"
            />
            <Button size="xs" onClick={() => setCreateOpen(true)}>New world</Button>
            </>)}
          </Group>
          <Group gap="xs">
            {world && view === 'worlds' && <WorldControls world={world} connected={stream.connected} onUpdate={stream.setWorld} onError={setError} />}
            <Tooltip label="Toggle light/dark">
              <ActionIcon variant="default" onClick={toggleColorScheme} aria-label="Toggle colour scheme">
                {colorScheme === 'dark' ? '☀' : '☾'}
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        {view === 'experiments' && (
          <ExperimentsPage onOpenWorld={(id) => { setWorldId(id); setView('worlds'); setTab('world'); }} />
        )}
        {view === 'worlds' && (<>
        {error && (
          <Notification color="red" onClose={() => setError(null)} mb="sm" title="Error">{error}</Notification>
        )}
        {!worldId && (
          <Card withBorder maw={640} mx="auto" mt="xl" padding="lg">
            <Title order={3} mb="xs">No world yet</Title>
            <Text size="sm" mb="md">
              Create a world to start a simulation. Agents follow deterministic world rules; their decisions come from a
              rule-based policy or, optionally, from Claude via the backend.
            </Text>
            <Button onClick={() => setCreateOpen(true)}>Create a world</Button>
          </Card>
        )}
        {worldId && !world && <Text c="dimmed">Loading world…</Text>}
        {world && (
          <Tabs value={tab} onChange={setTab} keepMounted={false}>
            <Tabs.List mb="sm">
              <Tabs.Tab value="world">World</Tabs.Tab>
              <Tabs.Tab value="society">Society</Tabs.Tab>
              <Tabs.Tab value="mind">Mind</Tabs.Tab>
              <Tabs.Tab value="analytics">Analytics</Tabs.Tab>
              <Tabs.Tab value="llm">LLM usage</Tabs.Tab>
              <Group ml="auto" gap="xs">
                <Badge variant="outline">{world.name}</Badge>
                <Button size="compact-xs" variant="subtle" color="red" onClick={deleteWorld}>Delete world</Button>
              </Group>
            </Tabs.List>

            <Tabs.Panel value="world">
              <Grid gutter="sm">
                <Grid.Col span={{ base: 12, lg: 8 }}>
                  <Stack gap="sm">
                    <Card withBorder padding={0} style={{ position: 'relative', height: 'min(66vh, 720px)', minHeight: 380, overflow: 'hidden' }}>
                      <WorldCanvas world={world} selectedId={selected} onSelect={setSelected}
                        tickIntervalMs={tickIntervalMs} thoughts={thoughts} />
                    </Card>
                    <Group justify="space-between">
                      <Legend />
                      <Group gap={6}>
                        <Text size="xs" c="dimmed">Intentions</Text>
                        <SegmentedControl size="xs" value={thoughts} onChange={(v) => setThoughts(v as ThoughtMode)}
                          data={[{ value: 'off', label: 'Off' }, { value: 'selected', label: 'Selected' }, { value: 'all', label: 'All' }]} />
                      </Group>
                    </Group>
                    <Card withBorder padding="sm">
                      <EventFeed events={stream.events} agentNames={agentNames} selectedAgent={selected}
                        onSelectAgent={setSelected} ticksPerDay={world.ticks_per_day} height={240} />
                    </Card>
                  </Stack>
                </Grid.Col>
                <Grid.Col span={{ base: 12, lg: 4 }}>
                  <Card withBorder padding="sm">
                    {selected ? (
                      <>
                        <Button size="compact-xs" variant="subtle" mb="xs" onClick={() => setSelected(null)}>← All agents</Button>
                        <AgentInspector worldId={world.id} agentId={selected} tick={world.tick} agentNames={agentNames} />
                      </>
                    ) : (
                      <>
                        <Text fw={600} mb="xs">Agents — click one to inspect</Text>
                        <Table fz="xs" highlightOnHover verticalSpacing={4}>
                          <Table.Thead>
                            <Table.Tr><Table.Th>Name</Table.Th><Table.Th>Doing</Table.Th><Table.Th>HP</Table.Th><Table.Th>Tokens</Table.Th></Table.Tr>
                          </Table.Thead>
                          <Table.Tbody>
                            {world.agents.map((a) => (
                              <Table.Tr key={a.id} onClick={() => setSelected(a.id)} style={{ cursor: 'pointer', opacity: a.alive ? 1 : 0.5 }}>
                                <Table.Td>
                                  <Group gap={4} wrap="nowrap">
                                    <Box w={8} h={8} style={{ borderRadius: 4, background: hex(MOOD_COLORS[a.alive ? a.mood : 'dead'] ?? 0xadb5bd) }} />
                                    {a.name}{a.controller === 'llm' && <Badge size="xs" color="violet" variant="light">LLM</Badge>}
                                  </Group>
                                </Table.Td>
                                <Table.Td>{a.alive ? a.action : 'dead'}</Table.Td>
                                <Table.Td>{a.health.toFixed(0)}</Table.Td>
                                <Table.Td>{a.tokens.toFixed(1)}</Table.Td>
                              </Table.Tr>
                            ))}
                          </Table.Tbody>
                        </Table>
                        {stream.metrics.length > 0 && (() => {
                          const m = stream.metrics[stream.metrics.length - 1];
                          return (
                            <Text size="xs" c="dimmed" mt="sm">
                              Alive {m.alive}/{m.population} · mean tokens {m.tokens_mean.toFixed(1)} · mean trust {m.trust_mean.toFixed(2)} · food in stock {m.food_stock_total}
                            </Text>
                          );
                        })()}
                      </>
                    )}
                  </Card>
                </Grid.Col>
              </Grid>
            </Tabs.Panel>

            <Tabs.Panel value="society">
              <SocietyPanel worldId={world.id} tick={world.tick} agents={world.agents} messages={stream.messages}
                latest={stream.metrics[stream.metrics.length - 1]}
                onSelectAgent={(id) => { setSelected(id); setTab('world'); }} />
            </Tabs.Panel>

            <Tabs.Panel value="mind">
              <MindPanel worldId={world.id} tick={world.tick} metrics={stream.metrics}
                onSelectAgent={(id) => { setSelected(id); setTab('world'); }} />
            </Tabs.Panel>

            <Tabs.Panel value="analytics">
              <Analytics metrics={stream.metrics} ticksPerDay={world.ticks_per_day} />
            </Tabs.Panel>

            <Tabs.Panel value="llm">
              <LLMPanel worldId={world.id} tick={world.tick} agentNames={agentNames} />
            </Tabs.Panel>
          </Tabs>
        )}
        {stream.error && <Alert color="red" mt="sm">{stream.error}</Alert>}
        </>)}
      </AppShell.Main>

      <CreateWorldModal opened={createOpen} onClose={() => setCreateOpen(false)}
        onCreated={(w) => { setWorldId(w.id); loadWorlds(); }} />
    </AppShell>
  );
}
