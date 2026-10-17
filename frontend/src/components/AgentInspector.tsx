import { useEffect, useRef, useState } from 'react';
import {
  Badge, Card, Group, Progress, ScrollArea, Stack, Table, Tabs, Text, Title, Tooltip,
} from '@mantine/core';
import { api } from '../api';
import type { AgentDetail } from '../types';
import { ACTION_COLORS, MOOD_COLORS, hex } from '../theme';

interface Props {
  worldId: string;
  agentId: string;
  tick: number;
  agentNames: Record<string, string>;
}

function Meter({ label, value, max = 100, color, invert = false }: { label: string; value: number; max?: number; color?: string; invert?: boolean }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const bad = invert ? pct > 70 : pct < 30;
  return (
    <div>
      <Group justify="space-between" gap={4}>
        <Text size="xs" c="dimmed">{label}</Text>
        <Text size="xs" fw={600}>{value.toFixed(max <= 1 ? 2 : 0)}</Text>
      </Group>
      <Progress value={pct} size="sm" color={color ?? (bad ? 'red' : 'teal')} aria-label={label} />
    </div>
  );
}

export function AgentInspector({ worldId, agentId, tick, agentNames }: Props) {
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [trustLog, setTrustLog] = useState<Awaited<ReturnType<typeof api.trustChanges>>>([]);
  const lastFetch = useRef(0);

  useEffect(() => {
    setAgent(null);
    lastFetch.current = 0;
  }, [agentId]);

  useEffect(() => {
    const now = performance.now();
    const wait = Math.max(0, 800 - (now - lastFetch.current));
    const t = setTimeout(() => {
      lastFetch.current = performance.now();
      api.agent(worldId, agentId).then((a) => { setAgent(a); setError(null); }).catch((e) => setError(String(e)));
      api.trustChanges(worldId, agentId).then(setTrustLog).catch(() => undefined);
    }, wait);
    return () => clearTimeout(t);
  }, [worldId, agentId, tick]);

  if (error) return <Text c="red" size="sm">{error}</Text>;
  if (!agent) return <Text size="sm" c="dimmed">Loading agent…</Text>;

  const name = (id: string) => agentNames[id] ?? id;
  const traits = Object.entries(agent.personality);
  const alloc = Object.entries(agent.time_allocation).sort((a, b) => b[1] - a[1]);
  const allocTotal = alloc.reduce((s, [, v]) => s + v, 0) || 1;
  const ex = agent.existential;

  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Title order={4}>{agent.name}</Title>
          <Text size="xs" c="dimmed">{agent.background}</Text>
        </div>
        <Stack gap={4} align="flex-end">
          <Badge color={agent.controller === 'llm' ? 'violet' : 'gray'} variant="light">
            {agent.controller === 'llm' ? 'LLM agent' : 'Rule agent'}
          </Badge>
          <Badge variant="dot" color={agent.alive ? 'green' : 'gray'} style={{ ['--badge-dot-color' as any]: hex(MOOD_COLORS[agent.current_mood] ?? 0xadb5bd) }}>
            {agent.alive ? agent.current_mood : 'dead'}
          </Badge>
        </Stack>
      </Group>

      {agent.death && (
        <Card withBorder padding="xs" bg="var(--mantine-color-red-light)">
          <Text size="sm">Died {agent.death.time} — {agent.death.cause.replace(/_/g, ' ')}. Last actions: {agent.death.last_actions.join(', ')}</Text>
        </Card>
      )}

      {agent.alive && (
        <Card withBorder padding="xs">
          <Text size="xs" c="dimmed">Doing</Text>
          <Text size="sm" fw={600}>{agent.current_action}</Text>
          {agent.visible_intention && <Text size="sm" fs="italic">“{agent.visible_intention}”</Text>}
          {agent.last_failure && <Text size="xs" c="orange">Last failure: {agent.last_failure}</Text>}
        </Card>
      )}

      <Tabs defaultValue="state" keepMounted={false}>
        <Tabs.List grow>
          <Tabs.Tab value="state">State</Tabs.Tab>
          <Tabs.Tab value="traits">Traits</Tabs.Tab>
          <Tabs.Tab value="social">Social</Tabs.Tab>
          <Tabs.Tab value="memory">Memory</Tabs.Tab>
          <Tabs.Tab value="decisions">Decisions</Tabs.Tab>
          <Tabs.Tab value="meaning">Meaning</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="state" pt="xs">
          <Stack gap={6}>
            <Group grow>
              <Meter label="Health" value={agent.health} />
              <Meter label="Energy" value={agent.energy} />
            </Group>
            <Group grow>
              <Meter label="Hunger" value={agent.hunger} invert />
              <div>
                <Text size="xs" c="dimmed">Tokens · Food · Knowledge</Text>
                <Text size="sm" fw={600}>{agent.tokens.toFixed(1)} · {agent.food} · {agent.knowledge.toFixed(1)}</Text>
              </div>
            </Group>
            <Text size="xs" fw={600} mt={4}>Temporary states</Text>
            <Group grow>
              {['stress', 'happiness', 'loneliness'].map((k) => (
                <Meter key={k} label={k} value={agent.emotions[k] ?? 0} max={1} color={k === 'happiness' ? 'teal' : 'orange'} />
              ))}
            </Group>
            <Group grow>
              {['frustration', 'overload', 'safety'].map((k) => (
                <Meter key={k} label={k} value={agent.emotions[k] ?? 0} max={1} color={k === 'safety' ? 'teal' : 'orange'} />
              ))}
            </Group>
            <Text size="xs" fw={600} mt={4}>Goals (salience)</Text>
            {agent.goals.map((g) => (
              <Group key={g.id} gap={6} wrap="nowrap">
                <Badge size="xs" variant={g.active ? 'filled' : 'outline'} w={86}>{g.id}</Badge>
                <Progress value={g.salience * 100} size="sm" style={{ flex: 1 }} aria-label={g.label} />
              </Group>
            ))}
            <Text size="xs" fw={600} mt={4}>Time allocation (lifetime ticks)</Text>
            <Progress.Root size="lg">
              {alloc.map(([k, v]) => (
                <Tooltip key={k} label={`${k}: ${v} (${((v / allocTotal) * 100).toFixed(0)}%)`}>
                  <Progress.Section value={(v / allocTotal) * 100} color={ACTION_COLORS[k] ?? 'gray'} />
                </Tooltip>
              ))}
            </Progress.Root>
            <Text size="xs" c="dimmed">
              Capacity: attention {agent.attention_capacity}/tick · messages {agent.communication_capacity}/tick · work {agent.work_ticks_today}/{agent.work_capacity} today
            </Text>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="traits" pt="xs">
          <Stack gap={4}>
            {traits.map(([t, v]) => {
              const changes = agent.trait_history.filter((h) => h.trait === t);
              const initial = agent.initial_personality?.[t] ?? (changes.length ? changes[0].old : v);
              const delta = v - initial;
              return (
                <Tooltip key={t} label={agent.trait_descriptions[t]} position="left">
                  <div>
                    <Group justify="space-between" gap={4}>
                      <Text size="xs">{t.replace(/_/g, ' ')}</Text>
                      <Text size="xs" fw={600}>
                        {v.toFixed(3)}
                        {Math.abs(delta) > 0.0005 && (
                          <Text span size="xs" c={delta > 0 ? 'teal' : 'orange'}> ({delta > 0 ? '+' : ''}{delta.toFixed(3)})</Text>
                        )}
                      </Text>
                    </Group>
                    <Progress value={v * 100} size="xs" aria-label={t} />
                  </div>
                </Tooltip>
              );
            })}
            <Text size="xs" c="dimmed" mt={4}>
              Experimental behavioural parameters, not psychological measurements. Changes are gradual and evidence-based.
            </Text>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="social" pt="xs">
          <Table striped withTableBorder fz="xs" verticalSpacing={4}>
            <Table.Thead>
              <Table.Tr><Table.Th>Agent</Table.Th><Table.Th>Trust</Table.Th><Table.Th>Fam.</Table.Th><Table.Th>Affinity</Table.Th></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {agent.relationships.map((r) => (
                <Table.Tr key={r.other_id}>
                  <Table.Td c={r.other_alive ? undefined : 'dimmed'}>{r.other_name}{r.other_alive ? '' : ' †'}</Table.Td>
                  <Table.Td>
                    <Tooltip label={`Beta(${r.trust_alpha.toFixed(1)}, ${r.trust_beta.toFixed(1)})`}>
                      <Text size="xs" c={r.trust > 0.55 ? 'teal' : r.trust < 0.45 ? 'red' : undefined}>{r.trust.toFixed(2)}</Text>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td>{r.familiarity}</Table.Td>
                  <Table.Td>{r.affinity.toFixed(2)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {agent.relationships.length === 0 && <Text size="sm" c="dimmed">Has not met anyone yet.</Text>}
          {trustLog.length > 0 && (
            <>
              <Text size="xs" fw={600} mt="xs">Trust evidence (latest first)</Text>
              <ScrollArea.Autosize mah={160}>
                {trustLog.slice().reverse().slice(0, 30).map((t, i) => (
                  <Text key={i} size="xs">
                    <Text span c="dimmed" size="xs">t{t.tick} </Text>
                    {name(t.agent_id)} → {name(t.other_id)}: {t.reason.replace(/_/g, ' ')}{' '}
                    <Text span size="xs" c={t.positive ? 'teal' : 'red'}>{t.trust_before.toFixed(2)} → {t.trust_after.toFixed(2)}</Text>
                  </Text>
                ))}
              </ScrollArea.Autosize>
            </>
          )}
          {agent.pending_offers.length > 0 && (
            <Text size="xs" mt="xs">Pending offers: {agent.pending_offers.length}</Text>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="memory" pt="xs">
          <ScrollArea.Autosize mah={360}>
            <Stack gap={4}>
              <Text size="xs" fw={600}>Life summary</Text>
              {agent.life_summary.slice(-5).map((l, i) => <Text key={i} size="xs">{l}</Text>)}
              <Text size="xs" fw={600} mt={4}>Working memory ({agent.memories.length} held, {agent.memory_archive_count} archived)</Text>
              {agent.memories.slice(0, 40).map((m) => (
                <Text key={m.id} size="xs" component="div">
                  <Badge size="xs" variant="light" mr={4}>{m.kind}</Badge>
                  <Text span size="xs" c="dimmed">t{m.tick} · {m.importance.toFixed(1)} </Text>
                  {m.content}
                  {m.related_agents.length > 0 && (
                    <Text span size="xs" c="dimmed"> [{m.related_agents.map(name).join(', ')}]</Text>
                  )}
                </Text>
              ))}
              <Text size="xs" fw={600} mt={4}>Recent observations</Text>
              {agent.short_term.slice(-10).reverse().map((o, i) => (
                <Text key={i} size="xs" c="dimmed">t{o.tick} {o.text}</Text>
              ))}
            </Stack>
          </ScrollArea.Autosize>
        </Tabs.Panel>

        <Tabs.Panel value="decisions" pt="xs">
          <ScrollArea.Autosize mah={360}>
            <Stack gap={6}>
              {agent.decisions.slice().reverse().map((d, i) => (
                <div key={i}>
                  <Group gap={4}>
                    <Text size="xs" c="dimmed">t{d.tick}</Text>
                    <Badge size="xs" color={d.source === 'llm' ? 'violet' : d.source === 'fallback' ? 'orange' : 'gray'}>{d.source}</Badge>
                    <Text size="xs" fw={600}>{String(d.proposal.action ?? '')}</Text>
                    {!d.valid && <Badge size="xs" color="red">rejected: {d.reason}</Badge>}
                    {d.applied_action && d.applied_action !== d.proposal.action && <Text size="xs">→ {d.applied_action}</Text>}
                    {d.existential_active && <Badge size="xs" color="grape" variant="light">existential</Badge>}
                    {d.latency_ms != null && <Text size="xs" c="dimmed">{Math.round(d.latency_ms)} ms</Text>}
                  </Group>
                  {d.visible_intention && <Text size="xs" fs="italic">“{d.visible_intention}”</Text>}
                  {d.fallback_reason && <Text size="xs" c="orange">fallback: {d.fallback_reason}</Text>}
                </div>
              ))}
            </Stack>
          </ScrollArea.Autosize>
        </Tabs.Panel>

        <Tabs.Panel value="meaning" pt="xs">
          <Stack gap={4}>
            <Text size="xs">
              Existential salience activated {ex.activations} of {ex.opportunities} decision opportunities
              ({ex.opportunities ? ((ex.activations / ex.opportunities) * 100).toFixed(1) : 0}%). Last probability {ex.last_probability.toFixed(3)}.
            </Text>
            <Text size="xs">Ticks contemplating: {ex.ticks_contemplating} · existential conversations: {ex.conversations}</Text>
            <Group grow>
              <Meter label="novelty" value={ex.novelty} max={1} color="cyan" />
              <Meter label="discussion" value={ex.discussion_exposure} max={1} color="grape" />
              <Meter label="uncertainty" value={ex.uncertainty} max={1} color="orange" />
            </Group>
            <Text size="xs" fw={600} mt={4}>Beliefs about purpose (as stated by the agent)</Text>
            {ex.beliefs.length === 0 && <Text size="xs" c="dimmed">No stated beliefs yet.</Text>}
            {ex.beliefs.slice().reverse().map((b, i) => (
              <Text key={i} size="xs"><Text span c="dimmed" size="xs">t{b.tick} </Text>{b.text}</Text>
            ))}
            <Text size="xs" c="dimmed" mt={4}>
              Statements are model outputs, not evidence of consciousness.
            </Text>
            {Object.keys(agent.stats).length > 0 && (
              <Text size="xs" c="dimmed">Messages sent {agent.stats.messages_sent ?? 0} · gifts {agent.stats.gifts_given ?? 0} · trades {agent.stats.trades_completed ?? 0} · artworks {agent.artworks}</Text>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
