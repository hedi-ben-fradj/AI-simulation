// Conversations: a list of who has been talking, and a chat-style transcript of one
// conversation (two agents or a group) with every message, its delivery status and
// the sender's intention at the time.
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge, Box, Button, Group, MultiSelect, Paper, ScrollArea, Select, Stack, Switch, Text, Tooltip, UnstyledButton,
} from '@mantine/core';
import { api } from '../api';
import type { AgentBrief, ConversationDetail, ConversationMessage, ConversationThread, Message, MessageStatus } from '../types';
import { Avatar } from './Avatar';

// Each participant gets a colour (by position in the conversation).
const PALETTE = ['teal', 'grape', 'orange', 'blue', 'pink', 'lime', 'cyan', 'red'];

const STATUS: Record<MessageStatus, { icon: string; label: (m: ConversationMessage) => string; color?: string }> = {
  read: { icon: '✓✓', label: (m) => `read ${m.read_time?.split(', ')[1] ?? ''}`.trim(), color: 'teal' },
  sending: { icon: '…', label: () => 'on its way' },
  unread: { icon: '•', label: () => 'delivered, not read yet', color: 'yellow' },
  never_read: { icon: '✗', label: () => 'never read (expired or inbox full)', color: 'red' },
  undelivered: { icon: '✗', label: () => 'not delivered (recipient died)', color: 'red' },
};

const clock = (time: string) => time.split(', ')[1] ?? time;
const day = (time: string) => time.split(', ')[0] ?? time;

function AvatarStack({ sprites, size = 26 }: { sprites: string[]; size?: number }) {
  return (
    <Group gap={0} wrap="nowrap" style={{ flexShrink: 0 }}>
      {sprites.slice(0, 4).map((s, i) => (
        <Box key={i} ml={i ? -size / 3 : 0} style={{ borderRadius: 7, boxShadow: '0 0 0 2px var(--mantine-color-body)' }}>
          <Avatar sprite={s} size={size} />
        </Box>
      ))}
    </Group>
  );
}

// ---------------------------------------------------------------- list

interface ListProps {
  worldId: string;
  tick: number;
  agents: AgentBrief[];
  filter: string | null;
  onFilter: (agentId: string | null) => void;
  onOpen: (participants: string[]) => void;
  /** Number of messages seen live; a change triggers a refresh. */
  liveMessageCount: number;
}

export function ConversationList({ worldId, tick, agents, filter, onFilter, onOpen, liveMessageCount }: ListProps) {
  const [threads, setThreads] = useState<ConversationThread[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const byId = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);

  useEffect(() => {
    const t = setTimeout(() => {
      api.conversations(worldId, filter).then((d) => { setThreads(d.conversations); setError(null); })
        .catch((e) => setError(String(e)));
    }, 250);
    return () => clearTimeout(t);
  }, [worldId, filter, liveMessageCount, Math.floor(tick / 6)]);

  const agentOptions = agents.map((a) => ({ value: a.id, label: a.alive ? a.name : `${a.name} †` }));
  return (
    <Stack gap="xs">
      <Group gap="xs" align="flex-end" grow>
        <Select size="xs" label="Involving" placeholder="Anyone" clearable data={agentOptions} value={filter}
          onChange={onFilter} />
      </Group>
      <Group gap="xs" align="flex-end" wrap="nowrap">
        <MultiSelect size="xs" label="Or focus on any agents" placeholder="Pick two or more" data={agentOptions}
          value={picked} onChange={setPicked} style={{ flex: 1 }} maxValues={8} searchable />
        <Button size="xs" disabled={picked.length < 2} onClick={() => onOpen(picked)}>Open</Button>
      </Group>
      {error && <Text size="xs" c="red">{error}</Text>}
      {threads === null && !error && <Text size="sm" c="dimmed">Loading…</Text>}
      {threads?.length === 0 && (
        <Text size="sm" c="dimmed">
          No conversations yet. Agents talk when they meet, need help or want to trade; cheap message costs and
          sociable personalities make them chattier.
        </Text>
      )}
      <ScrollArea.Autosize mah="min(62vh, 640px)" type="auto" offsetScrollbars>
        <Stack gap={6}>
          {threads?.map((t) => {
            const last = t.last_message;
            const sender = byId[last.sender_id]?.name ?? last.sender_id;
            return (
              <UnstyledButton key={t.id} onClick={() => onOpen(t.participants)} p={8}
                style={{ borderRadius: 8, border: '1px solid var(--mantine-color-default-border)' }}
                aria-label={`Conversation between ${t.names.join(', ')}`}>
                <Group gap="sm" wrap="nowrap" align="flex-start">
                  <AvatarStack sprites={t.participants.map((id) => byId[id]?.sprite ?? 'human-worker-red')} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Group gap={6} wrap="nowrap" justify="space-between">
                      <Text size="sm" fw={600} truncate>{t.names.join(t.group ? ', ' : ' & ')}</Text>
                      <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>{t.last_time}</Text>
                    </Group>
                    <Text size="xs" c="dimmed" lineClamp={2}>
                      <b>{sender}:</b> {last.content}
                    </Text>
                    <Group gap={4} mt={4}>
                      <Badge size="xs" variant="light">{t.message_count} message{t.message_count === 1 ? '' : 's'}</Badge>
                      {t.group && <Badge size="xs" variant="light" color="grape">group</Badge>}
                      {t.existential && <Badge size="xs" variant="light" color="violet">✦ about existence</Badge>}
                      {t.first_tick !== t.last_tick && <Text size="xs" c="dimmed">since {t.time}</Text>}
                    </Group>
                  </div>
                </Group>
              </UnstyledButton>
            );
          })}
        </Stack>
      </ScrollArea.Autosize>
    </Stack>
  );
}

// ---------------------------------------------------------- transcript

interface ViewProps {
  worldId: string;
  participants: string[];
  tick: number;
  running: boolean;
  liveMessages: Message[];
  onMap: boolean;
  onToggleMap: (on: boolean) => void;
  onClose: () => void;
  onSelectAgent: (id: string) => void;
}

type Item =
  | { kind: 'message'; tick: number; m: ConversationMessage }
  | { kind: 'event'; tick: number; text: string; type: string; time: string };

const EVENT_ICONS: Record<string, string> = {
  socialize: '🤝', give: '🎁', trade: '⚖', trade_offer: '📜', trade_rejected: '✋', trade_failed: '⚠', theft: '🗡',
};

export function ConversationView({
  worldId, participants, tick, running, liveMessages, onMap, onToggleMap, onClose, onSelectAgent,
}: ViewProps) {
  const [data, setData] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const key = participants.join(',');
  const members = useMemo(() => new Set(participants), [key]);
  // New live messages among these agents trigger an immediate refresh.
  const liveCount = useMemo(
    () => liveMessages.filter((m) => members.has(m.sender_id) && members.has(m.recipient_id)).length,
    [liveMessages, members]);

  useEffect(() => {
    setData(null);
    stick.current = true;
  }, [key]);
  useEffect(() => {
    const t = setTimeout(() => {
      api.conversation(worldId, participants).then((d) => { setData(d); setError(null); })
        .catch((e) => setError(String(e)));
    }, 200);
    return () => clearTimeout(t);
  }, [worldId, key, liveCount, Math.floor(tick / 3)]);

  // Keep the newest message in view unless the reader scrolled up.
  useEffect(() => {
    const el = viewport.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [data]);

  const colorOf = useMemo(() => Object.fromEntries(participants.map((id, i) => [id, PALETTE[i % PALETTE.length]])), [key]);
  const people = data?.participants ?? [];
  const nameOf = (id: string) => people.find((p) => p.id === id)?.name ?? id;
  const spriteOf = (id: string) => people.find((p) => p.id === id)?.sprite ?? 'human-worker-red';
  const pair = participants.length === 2;

  const items: Item[] = useMemo(() => {
    if (!data) return [];
    const list: Item[] = [
      ...data.messages.map((m) => ({ kind: 'message' as const, tick: m.sent_tick, m })),
      ...data.events.map((e) => ({ kind: 'event' as const, tick: e.tick, text: e.summary, type: e.type, time: e.time })),
    ];
    // Messages are sent before the tick's activities happen.
    return list.sort((a, b) => a.tick - b.tick || (a.kind === b.kind ? 0 : a.kind === 'message' ? -1 : 1));
  }, [data]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const m of data?.messages ?? []) c[m.sender_id] = (c[m.sender_id] ?? 0) + 1;
    return c;
  }, [data]);

  let lastDay = '';
  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="nowrap">
        <Button size="compact-xs" variant="subtle" onClick={onClose}>← All conversations</Button>
        <Switch size="xs" label="Focus on map" checked={onMap} onChange={(e) => onToggleMap(e.currentTarget.checked)} />
      </Group>
      <Group gap="xs" wrap="wrap">
        {participants.map((id) => (
          <UnstyledButton key={id} onClick={() => onSelectAgent(id)} aria-label={`Inspect ${nameOf(id)}`}>
            <Group gap={6} wrap="nowrap" px={6} py={3}
              style={{ borderRadius: 8, background: `var(--mantine-color-${colorOf[id]}-light)` }}>
              <Avatar sprite={spriteOf(id)} size={24} dead={people.find((p) => p.id === id)?.alive === false} />
              <Text size="sm" fw={600}>{nameOf(id)}</Text>
              {people.find((p) => p.id === id)?.controller === 'llm' && <Badge size="xs" color="violet" variant="light">LLM</Badge>}
              <Text size="xs" c="dimmed">{counts[id] ?? 0}</Text>
            </Group>
          </UnstyledButton>
        ))}
      </Group>
      <Group gap={6}>
        <Text size="xs" c="dimmed">
          {data ? `${data.messages.length} message${data.messages.length === 1 ? '' : 's'}` : 'Loading…'}
          {data && data.events.length > 0 && ` · ${data.events.length} interaction${data.events.length === 1 ? '' : 's'}`}
        </Text>
        {running && <Badge size="xs" variant="dot" color="green">live</Badge>}
      </Group>
      {error && <Text size="xs" c="red">{error}</Text>}

      <ScrollArea h="min(58vh, 600px)" type="auto" offsetScrollbars viewportRef={viewport}
        onScrollPositionChange={({ y }) => {
          const el = viewport.current;
          if (el) stick.current = el.scrollHeight - el.clientHeight - y < 40;
        }}>
        <Stack gap={8} pr={4}>
          {data && items.length === 0 && (
            <Text size="sm" c="dimmed" ta="center" mt="lg">
              No messages between {participants.map(nameOf).join(pair ? ' and ' : ', ')} yet.
              New ones appear here as they are sent.
            </Text>
          )}
          {items.map((it, i) => {
            const time = it.kind === 'message' ? it.m.time : it.time;
            const d = day(time);
            const separator = d !== lastDay ? <Text key={`d${i}`} size="xs" c="dimmed" ta="center" fw={600} mt={4}>— {d} —</Text> : null;
            lastDay = d;
            if (it.kind === 'event') {
              return (
                <Fragment key={`e${i}`}>
                  {separator}
                  <Text size="xs" c="dimmed" ta="center" fs="italic">
                    {EVENT_ICONS[it.type] ?? '•'} {it.text} · {clock(it.time)}
                  </Text>
                </Fragment>
              );
            }
            const m = it.m;
            const right = pair && m.sender_id === participants[1];
            const st = STATUS[m.status];
            return (
              <Fragment key={m.id}>
                {separator}
                <Group gap={8} wrap="nowrap" align="flex-start" style={{ flexDirection: right ? 'row-reverse' : 'row' }}>
                  <UnstyledButton onClick={() => onSelectAgent(m.sender_id)} aria-label={`Inspect ${m.sender_name}`}>
                    <Avatar sprite={spriteOf(m.sender_id)} size={30} />
                  </UnstyledButton>
                  <Box maw="85%" style={{ minWidth: 0 }}>
                    <Group gap={6} wrap="nowrap" justify={right ? 'flex-end' : 'flex-start'}>
                      <Text size="xs" fw={700} c={`${colorOf[m.sender_id]}.7`}>{m.sender_name}</Text>
                      {!pair && <Text size="xs" c="dimmed">→ {m.recipient_name}</Text>}
                      <Text size="xs" c="dimmed">{clock(m.time)}</Text>
                    </Group>
                    <Paper px={10} py={6} radius="md" withBorder
                      style={{ background: `var(--mantine-color-${colorOf[m.sender_id]}-light)`,
                        borderColor: `var(--mantine-color-${colorOf[m.sender_id]}-light-color)` }}>
                      <Text size="sm" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{m.content}</Text>
                    </Paper>
                    <Group gap={6} mt={2} justify={right ? 'flex-end' : 'flex-start'} wrap="wrap">
                      <Tooltip label={`${m.tokens} tokens long · cost ${m.token_cost.toFixed(2)} tokens · delivered ${m.deliver_tick > m.sent_tick ? 'next hour' : 'immediately'}`}>
                        <Text size="xs" c={st.color ? `${st.color}.7` : 'dimmed'}>{st.icon} {st.label(m)}</Text>
                      </Tooltip>
                      {m.existential && <Badge size="xs" variant="light" color="violet">✦ existence</Badge>}
                    </Group>
                    {m.intention && m.intention !== m.content && (
                      <Text size="xs" c="dimmed" fs="italic" ta={right ? 'right' : 'left'}>💭 {m.intention}</Text>
                    )}
                  </Box>
                </Group>
              </Fragment>
            );
          })}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
