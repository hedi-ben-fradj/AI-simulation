import { useEffect, useMemo, useState } from 'react';
import {
  Badge, Card, Grid, Group, ScrollArea, Select, Stack, Table, Text, Tooltip, useComputedColorScheme,
} from '@mantine/core';
import { api } from '../api';
import type { AgentBrief, Message, Metrics } from '../types';
import { trustColor } from '../theme';

interface Props {
  worldId: string;
  tick: number;
  agents: AgentBrief[];
  messages: Message[];
  latest: Metrics | undefined;
  onSelectAgent: (id: string) => void;
}

type Rel = { agent_id: string; other_id: string; trust: number; familiarity: number; affinity: number };

function TrustLegend({ scheme }: { scheme: 'light' | 'dark' }) {
  const stops = [0.2, 0.35, 0.5, 0.65, 0.8];
  return (
    <Group gap={4} align="center">
      <Text size="xs" c="dimmed">distrust</Text>
      {stops.map((s) => (
        <Tooltip key={s} label={`trust ${s}`}>
          <div style={{ width: 18, height: 10, borderRadius: 2, background: trustColor(s, scheme), border: '1px solid var(--mantine-color-default-border)' }} />
        </Tooltip>
      ))}
      <Text size="xs" c="dimmed">trust · 0.5 = no evidence yet</Text>
    </Group>
  );
}

function Network({ agents, rels, scheme, onSelect }: { agents: AgentBrief[]; rels: Rel[]; scheme: 'light' | 'dark'; onSelect: (id: string) => void }) {
  const [hover, setHover] = useState<string | null>(null);
  const size = 420;
  const c = size / 2;
  const r = size / 2 - 50;
  const pos = new Map(agents.map((a, i) => {
    const ang = (2 * Math.PI * i) / Math.max(1, agents.length) - Math.PI / 2;
    return [a.id, { x: c + r * Math.cos(ang), y: c + r * Math.sin(ang) }];
  }));
  const maxFam = Math.max(1, ...rels.map((e) => e.familiarity));
  const shown = rels.filter((e) => e.familiarity > 0 || Math.abs(e.trust - 0.5) > 0.03);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" style={{ maxHeight: 460 }} role="img" aria-label="Trust network">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--mantine-color-dimmed)" />
        </marker>
      </defs>
      {shown.map((e) => {
        const a = pos.get(e.agent_id);
        const b = pos.get(e.other_id);
        if (!a || !b) return null;
        // Offset the two directions of a pair so both are visible.
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.hypot(dx, dy) || 1;
        const ox = (-dy / len) * 4;
        const oy = (dx / len) * 4;
        const shrink = 16 / len;
        const dim = hover && hover !== e.agent_id && hover !== e.other_id;
        return (
          <line key={`${e.agent_id}-${e.other_id}`}
            x1={a.x + ox + dx * shrink} y1={a.y + oy + dy * shrink} x2={b.x + ox - dx * shrink} y2={b.y + oy - dy * shrink}
            stroke={trustColor(e.trust, scheme)} strokeWidth={1.5 + 3.5 * (e.familiarity / maxFam)} strokeLinecap="round"
            opacity={dim ? 0.12 : 0.9} markerEnd="url(#arrow)">
            <title>{`${e.agent_id} → ${e.other_id}: trust ${e.trust.toFixed(2)}, familiarity ${e.familiarity}`}</title>
          </line>
        );
      })}
      {agents.map((a) => {
        const p = pos.get(a.id)!;
        return (
          <g key={a.id} transform={`translate(${p.x},${p.y})`} style={{ cursor: 'pointer' }}
            onMouseEnter={() => setHover(a.id)} onMouseLeave={() => setHover(null)} onClick={() => onSelect(a.id)}>
            <circle r={12} fill={a.alive ? 'var(--mantine-color-body)' : 'var(--mantine-color-default-hover)'}
              stroke={a.controller === 'llm' ? '#7950f2' : 'var(--mantine-color-default-border)'} strokeWidth={2} />
            <text textAnchor="middle" dy={4} fontSize={10} fill="var(--mantine-color-text)">{a.name.slice(0, 2)}</text>
            <text textAnchor="middle" dy={26} fontSize={11} fill="var(--mantine-color-text)" opacity={a.alive ? 1 : 0.5}>
              {a.name}{a.alive ? '' : ' †'}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function SocietyPanel({ worldId, tick, agents, messages, latest, onSelectAgent }: Props) {
  const scheme = useComputedColorScheme('light');
  const [rels, setRels] = useState<Rel[]>([]);
  const [pair, setPair] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => api.relationships(worldId).then(setRels).catch(() => undefined), 250);
    return () => clearTimeout(t);
  }, [worldId, Math.floor(tick / 2)]);

  const names = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a.name])), [agents]);
  const trustOf = useMemo(() => new Map(rels.map((e) => [`${e.agent_id}|${e.other_id}`, e])), [rels]);

  const conversations = useMemo(() => {
    const groups = new Map<string, Message[]>();
    for (const m of messages) {
      const key = [m.sender_id, m.recipient_id].sort().join('|');
      groups.set(key, [...(groups.get(key) ?? []), m]);
    }
    return groups;
  }, [messages]);
  const pairOptions = Array.from(conversations.entries())
    .sort((a, b) => b[1].length - a[1].length)
    .map(([k, v]) => ({ value: k, label: `${k.split('|').map((id) => names[id] ?? id).join(' ↔ ')} (${v.length})` }));
  const shownMessages = (pair ? conversations.get(pair) ?? [] : messages).slice(-80).reverse();

  return (
    <Stack gap="sm">
      {latest && (
        <Group gap="xs">
          <Badge variant="light">friendships {String(latest.friendships ?? 0)}</Badge>
          <Badge variant="light" color="red">hostile pairs {String(latest.hostile_pairs ?? 0)}</Badge>
          <Badge variant="light" color="gray">isolated {String(latest.isolated_agents ?? 0)}</Badge>
          <Badge variant="light" color="teal">network density {Number(latest.network_density ?? 0).toFixed(2)}</Badge>
          <Badge variant="light" color="indigo">mean trust {latest.trust_mean.toFixed(2)}</Badge>
        </Group>
      )}
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="sm">
            <Text fw={600} size="sm">Trust network</Text>
            <Text size="xs" c="dimmed" mb={4}>Arrow = who trusts whom; colour = trust; width = familiarity. Click a person to inspect.</Text>
            <Network agents={agents} rels={rels} scheme={scheme} onSelect={onSelectAgent} />
            <TrustLegend scheme={scheme} />
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="sm">
            <Text fw={600} size="sm" mb={4}>Trust matrix (row trusts column)</Text>
            <ScrollArea>
              <Table fz="xs" withColumnBorders verticalSpacing={2} horizontalSpacing={4}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th />
                    {agents.map((a) => <Table.Th key={a.id} style={{ textAlign: 'center' }}>{a.name.slice(0, 4)}</Table.Th>)}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {agents.map((row) => (
                    <Table.Tr key={row.id}>
                      <Table.Td fw={600}>{row.name}</Table.Td>
                      {agents.map((col) => {
                        if (col.id === row.id) return <Table.Td key={col.id} />;
                        const e = trustOf.get(`${row.id}|${col.id}`);
                        return (
                          <Tooltip key={col.id} label={e ? `${row.name} → ${col.name}: trust ${e.trust.toFixed(2)}, familiarity ${e.familiarity}` : `${row.name} has not met ${col.name}`}>
                            <Table.Td style={{ background: e ? trustColor(e.trust, scheme) : undefined, textAlign: 'center' }}>
                              {e ? e.trust.toFixed(2) : '–'}
                            </Table.Td>
                          </Tooltip>
                        );
                      })}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </Card>
          <Card withBorder padding="sm" mt="sm">
            <Group justify="space-between" mb={4}>
              <Text fw={600} size="sm">Conversations</Text>
              <Select size="xs" placeholder="All messages" data={pairOptions} value={pair} onChange={setPair} clearable w={240} />
            </Group>
            <ScrollArea h={260}>
              <Stack gap={4}>
                {shownMessages.length === 0 && <Text size="xs" c="dimmed">No messages yet.</Text>}
                {shownMessages.map((m) => (
                  <Text key={m.id} size="xs">
                    <Text span c="dimmed" size="xs">t{m.sent_tick} </Text>
                    <Text span fw={600} size="xs">{names[m.sender_id] ?? m.sender_id} → {names[m.recipient_id] ?? m.recipient_id}: </Text>
                    {m.content}
                    <Text span c="dimmed" size="xs"> ({m.tokens} tok, cost {m.token_cost.toFixed(3)}){m.existential ? ' · existential' : ''}</Text>
                  </Text>
                ))}
              </Stack>
            </ScrollArea>
          </Card>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
