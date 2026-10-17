import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon, Alert, AppShell, Badge, Box, Button, Card, Grid, Group, Notification, Progress, SegmentedControl, Select, Stack, Tabs, Text,
  UnstyledButton,
  Title, Tooltip, useMantineColorScheme,
} from '@mantine/core';
import { api } from './api';
import { useWorldStream } from './hooks/useWorldStream';
import { WorldCanvas, type ThoughtMode } from './components/WorldCanvas';
import { WorldControls } from './components/WorldControls';
import { SetupPage } from './components/SetupPage';
import { AgentInspector } from './components/AgentInspector';
import { EventFeed } from './components/EventFeed';
import { Analytics } from './components/Analytics';
import { LLMPanel } from './components/LLMPanel';
import { SocietyPanel } from './components/SocietyPanel';
import { ConversationList, ConversationView } from './components/Conversations';
import { MindPanel } from './components/MindPanel';
import { ExperimentsPage } from './components/ExperimentsPage';
import type { WorldSummary, WorldView } from './types';
import { MOOD_COLORS, hex } from './theme';
import { ACTION_EMOTES, ARCHETYPE_LABELS } from './sprites';
import { Avatar } from './components/Avatar';

const WORLD_KEY = 'aisim.world';

type View = 'setup' | 'worlds' | 'experiments';

function initialView(): View {
  const hash = window.location.hash.replace(/^#/, '');
  if (hash === 'experiments') return 'experiments';
  return hash && hash !== 'setup' ? 'worlds' : 'setup';
}

function readStoredWorld(): string | null {
  const fromHash = window.location.hash.replace(/^#/, '');
  if (fromHash && fromHash !== 'experiments' && fromHash !== 'setup') return fromHash;
  try {
    return localStorage.getItem(WORLD_KEY);
  } catch {
    return null;
  }
}

function Legend() {
  const examples: [string, string][] = [
    ['human-worker-red', 'human-worker'], ['mage-cyan', 'mage'], ['archer-green', 'archer'], ['warrior-red', 'warrior'],
    ['soldier-blue', 'soldier'], ['human-soldier-cyan', 'human-soldier'], ['orc-peon-red', 'orc'],
  ];
  return (
    <Stack gap={6}>
      <Group gap="md" wrap="wrap">
        <Text size="xs" fw={600}>Who's who</Text>
        {examples.map(([sheet, kind]) => (
          <Tooltip key={kind} label={ARCHETYPE_LABELS[kind]}>
            <Group gap={4} wrap="nowrap"><Avatar sprite={sheet} size={22} /><Text size="xs">{ARCHETYPE_LABELS[kind].split(' — ')[0]}</Text></Group>
          </Tooltip>
        ))}
        <Text size="xs" c="dimmed">appearance = strongest starting trait (hover)</Text>
      </Group>
      <Group gap="md" wrap="wrap">
        <Text size="xs" fw={600}>Mood dot</Text>
        {['content', 'calm', 'contemplative', 'lonely', 'stressed', 'starving', 'exhausted'].map((m) => (
          <Group key={m} gap={4}><Box w={9} h={9} style={{ borderRadius: 5, background: hex(MOOD_COLORS[m]) }} /><Text size="xs">{m}</Text></Group>
        ))}
        <Text size="xs" c="dimmed">◆ = Claude/LLM agent · violet glow = pondering existence · drag to pan, scroll to zoom</Text>
      </Group>
    </Stack>
  );
}

function AgentRoster({ agents, onSelect }: { agents: WorldView['agents']; onSelect: (id: string) => void }) {
  return (
    <Stack gap={4}>
      {agents.map((a) => (
        <UnstyledButton key={a.id} onClick={() => onSelect(a.id)} p={6}
          style={{ borderRadius: 6, opacity: a.alive ? 1 : 0.55, border: '1px solid var(--mantine-color-default-border)' }}>
          <Group gap="sm" wrap="nowrap">
            <Avatar sprite={a.sprite} size={34} dead={!a.alive} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <Group gap={6} wrap="nowrap">
                <Box w={8} h={8} style={{ borderRadius: 4, flexShrink: 0, background: hex(MOOD_COLORS[a.alive ? a.mood : 'dead'] ?? 0xadb5bd) }} />
                <Text size="sm" fw={600} truncate>{a.name}</Text>
                {a.controller === 'llm' && <Badge size="xs" color="violet" variant="light">LLM</Badge>}
                <Text size="xs" c="dimmed" ml="auto" style={{ whiteSpace: 'nowrap' }}>
                  {a.alive ? `${ACTION_EMOTES[a.action] ?? ''} ${a.traveling ? `→ ${a.action}` : a.action}` : '🪦 dead'}
                </Text>
              </Group>
              {a.alive && (
                <Group gap={6} mt={4} wrap="nowrap">
                  <Progress value={a.health} size="sm" color={a.health > 50 ? 'teal' : a.health > 25 ? 'yellow' : 'red'} style={{ flex: 1 }}
                    aria-label="health" title={`health ${Math.round(a.health)}`} />
                  <Text size="xs" c="dimmed" ta="right" style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>{a.tokens.toFixed(1)} tokens</Text>
                </Group>
              )}
            </div>
          </Group>
        </UnstyledButton>
      ))}
    </Stack>
  );
}

export default function App() {
  const [worlds, setWorlds] = useState<WorldSummary[]>([]);
  const [worldId, setWorldId] = useState<string | null>(readStoredWorld);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<string | null>('world');
  // The app opens on the setup page unless the URL points at a world or the experiments page.
  const [view, setView] = useState<View>(initialView);
  const [thoughts, setThoughts] = useState<ThoughtMode>('all');
  // Right-hand panel of the World tab, and the conversation being read (if any).
  const [side, setSide] = useState<'villagers' | 'conversations'>('villagers');
  const [conversation, setConversation] = useState<string[] | null>(null);
  const [conversationFilter, setConversationFilter] = useState<string | null>(null);
  const [focusOnMap, setFocusOnMap] = useState(true);
  const stream = useWorldStream(view === 'worlds' ? worldId : null);
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();

  const loadWorlds = useCallback(() => {
    api.worlds().then((ws) => {
      setWorlds(ws);
      setWorldId((cur) => (cur && ws.some((w) => w.id === cur) ? cur : ws.find((w) => !w.experiment_id)?.id ?? null));
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(loadWorlds, [loadWorlds]);
  useEffect(() => {
    setSelected(null);
    setConversation(null);
    setConversationFilter(null);
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
    if (view === 'setup') window.history.replaceState(null, '', '#setup');
  }, [view]);
  const openWorld = (id: string) => {
    setWorldId(id);
    setView('worlds');
    setTab('world');
  };

  const world = stream.world;
  const agentNames = useMemo(() => Object.fromEntries((world?.agents ?? []).map((a) => [a.id, a.name])), [world?.agents]);
  const agentSprites = useMemo(() => Object.fromEntries((world?.agents ?? []).map((a) => [a.id, a.sprite ?? ''])), [world?.agents]);
  const tickIntervalMs = world && world.speed > 0 ? 1000 / world.speed : 250;

  const openConversation = (participants: string[]) => {
    setConversation(participants);
    setFocusOnMap(true);
    setSide('conversations');
    setTab('world');
  };
  const openConversationsOf = (agentId: string) => {
    setConversationFilter(agentId);
    setConversation(null);
    setSide('conversations');
    setTab('world');
  };
  const inspect = (id: string | null) => {
    setSelected(id);
    if (id) setSide('villagers');
  };

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
            <Group gap={6} wrap="nowrap">
              <Avatar sprite="mage-red" size={30} />
              <Title order={3} style={{ whiteSpace: 'nowrap' }}>Agent Civilization</Title>
            </Group>
            <SegmentedControl size="xs" value={view} onChange={(v) => setView(v as View)}
              data={[{ value: 'setup', label: 'New simulation' }, { value: 'worlds', label: 'Worlds' }, { value: 'experiments', label: 'Experiments' }]} />
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
        {view === 'setup' && (
          <SetupPage worlds={worlds} onOpenWorld={openWorld} onCreated={(w) => { loadWorlds(); openWorld(w.id); }} />
        )}
        {view === 'experiments' && <ExperimentsPage onOpenWorld={openWorld} />}
        {view === 'worlds' && (<>
        {error && (
          <Notification color="red" onClose={() => setError(null)} mb="sm" title="Error">{error}</Notification>
        )}
        {!worldId && (
          <Card withBorder maw={640} mx="auto" mt="xl" padding="lg">
            <Title order={3} mb="xs">No world yet</Title>
            <Text size="sm" mb="md">
              Set up a simulation to start. Agents follow deterministic world rules; their decisions come from a
              rule-based policy or, optionally, from Claude via the backend.
            </Text>
            <Button onClick={() => setView('setup')}>Set up a simulation</Button>
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
                      <WorldCanvas world={world} selectedId={selected} onSelect={inspect}
                        tickIntervalMs={tickIntervalMs} thoughts={thoughts}
                        focus={conversation && focusOnMap ? conversation : null} onClearFocus={() => setFocusOnMap(false)} />
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
                      <EventFeed events={stream.events} agentNames={agentNames} agentSprites={agentSprites} selectedAgent={selected}
                        onSelectAgent={inspect} onOpenConversation={openConversation} ticksPerDay={world.ticks_per_day} height={240} />
                    </Card>
                  </Stack>
                </Grid.Col>
                <Grid.Col span={{ base: 12, lg: 4 }}>
                  <Card withBorder padding="sm">
                    <SegmentedControl fullWidth size="xs" mb="sm" value={side} onChange={(v) => setSide(v as typeof side)}
                      data={[{ value: 'villagers', label: 'Villagers' }, { value: 'conversations', label: '💬 Conversations' }]} />
                    {side === 'conversations' ? (
                      conversation ? (
                        <ConversationView worldId={world.id} participants={conversation} tick={world.tick}
                          running={world.status === 'running'} liveMessages={stream.messages}
                          onMap={focusOnMap} onToggleMap={setFocusOnMap}
                          onClose={() => setConversation(null)} onSelectAgent={inspect} />
                      ) : (
                        <ConversationList worldId={world.id} tick={world.tick} agents={world.agents}
                          filter={conversationFilter} onFilter={setConversationFilter} onOpen={openConversation}
                          liveMessageCount={stream.messages.length} />
                      )
                    ) : selected ? (
                      <>
                        <Group gap="xs" mb="xs">
                          <Button size="compact-xs" variant="subtle" onClick={() => setSelected(null)}>← All agents</Button>
                          {conversation && (
                            <Button size="compact-xs" variant="subtle" onClick={() => setSide('conversations')}>💬 Back to the conversation</Button>
                          )}
                        </Group>
                        <AgentInspector worldId={world.id} agentId={selected} tick={world.tick} agentNames={agentNames}
                          onOpenConversations={openConversationsOf} />
                      </>
                    ) : (
                      <>
                        <Title order={5} mb="xs">Villagers — click one to inspect</Title>
                        <AgentRoster agents={world.agents} onSelect={inspect} />
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
                onSelectAgent={(id) => { inspect(id); setTab('world'); }} onOpenConversation={openConversation} />
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

    </AppShell>
  );
}
