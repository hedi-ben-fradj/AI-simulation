import { useMemo, useState } from 'react';
import { Badge, Chip, Group, ScrollArea, Stack, Text } from '@mantine/core';
import type { SimEvent } from '../types';
import { Avatar } from './Avatar';

interface Props {
  events: SimEvent[];
  agentNames: Record<string, string>;
  /** Character sheet per agent id, for the row avatars. */
  agentSprites?: Record<string, string>;
  selectedAgent: string | null;
  onSelectAgent: (id: string) => void;
  height?: number | string;
  ticksPerDay: number;
}

const GROUPS: Record<string, string[]> = {
  life: ['death', 'birth', 'hazard', 'discovery'],
  social: ['socialize', 'give', 'trade', 'trade_offer', 'trade_rejected', 'trade_failed', 'theft'],
  messages: ['message'],
  economy: ['work', 'eat', 'buy_food'],
  mind: ['reflect', 'create', 'study', 'belief_update', 'existential_activation', 'trait_change'],
  system: ['action_rejected', 'action_failed', 'message_dropped', 'message_expired'],
};

const TYPE_COLORS: Record<string, string> = {
  death: 'red', birth: 'green', hazard: 'orange', discovery: 'cyan', theft: 'red', give: 'teal', trade: 'lime',
  trade_offer: 'lime', trade_rejected: 'orange', message: 'pink', reflect: 'grape', belief_update: 'violet',
  existential_activation: 'grape', action_rejected: 'yellow', action_failed: 'yellow', socialize: 'pink',
};

const IMPORTANT_DEFAULT = ['life', 'social', 'messages', 'mind'];

export function EventFeed({ events, agentNames, agentSprites = {}, selectedAgent, onSelectAgent, height = 260, ticksPerDay }: Props) {
  const [groups, setGroups] = useState<string[]>(IMPORTANT_DEFAULT);
  const [onlySelected, setOnlySelected] = useState(false);

  const allowed = useMemo(() => new Set(groups.flatMap((g) => GROUPS[g] ?? [])), [groups]);
  const shown = useMemo(() => {
    const out = events.filter((e) => allowed.has(e.type) && (!onlySelected || !selectedAgent || e.agent_id === selectedAgent || e.target_id === selectedAgent || e.participants.includes(selectedAgent)));
    return out.slice(-200).reverse();
  }, [events, allowed, onlySelected, selectedAgent]);

  const time = (tick: number) => {
    const day = Math.floor(tick / ticksPerDay) + 1;
    const mins = Math.round(((tick % ticksPerDay) * 24 * 60) / ticksPerDay);
    return `D${day} ${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`;
  };

  return (
    <Stack gap={6} h="100%">
      <Group gap={6} justify="space-between">
        <Chip.Group multiple value={groups} onChange={setGroups}>
          <Group gap={4}>
            {Object.keys(GROUPS).map((g) => (
              <Chip key={g} value={g} size="xs" variant="light">{g}</Chip>
            ))}
          </Group>
        </Chip.Group>
        {selectedAgent && (
          <Chip size="xs" checked={onlySelected} onChange={setOnlySelected}>
            only {agentNames[selectedAgent]}
          </Chip>
        )}
      </Group>
      <ScrollArea h={height} type="auto" offsetScrollbars>
        <Stack gap={2}>
          {shown.length === 0 && <Text size="sm" c="dimmed">No events yet.</Text>}
          {shown.map((e, i) => (
            <Group key={`${e.tick}-${i}-${e.type}`} gap={6} wrap="nowrap" align="flex-start">
              <Text size="xs" c="dimmed" ff="monospace" style={{ flexShrink: 0 }}>{time(e.tick)}</Text>
              {e.agent_id && agentSprites[e.agent_id]
                ? <Avatar sprite={agentSprites[e.agent_id]} size={18} title={agentNames[e.agent_id]} />
                : <div style={{ width: 18, flexShrink: 0 }} />}
              <Badge size="xs" variant="light" color={TYPE_COLORS[e.type] ?? 'gray'} style={{ flexShrink: 0 }}>{e.type.replace(/_/g, ' ')}</Badge>
              <Text
                size="xs"
                style={{ cursor: e.agent_id ? 'pointer' : undefined }}
                onClick={() => e.agent_id && onSelectAgent(e.agent_id)}
              >
                {e.summary}
                {e.visibility === 'private' && <Text span size="xs" c="dimmed"> (private)</Text>}
              </Text>
            </Group>
          ))}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
