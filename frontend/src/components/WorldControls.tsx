import { useState } from 'react';
import { ActionIcon, Badge, Button, Group, SegmentedControl, Text, Tooltip } from '@mantine/core';
import { api } from '../api';
import type { WorldView } from '../types';

interface Props {
  world: WorldView;
  connected: boolean;
  onUpdate: (w: WorldView) => void;
  onError: (msg: string) => void;
}

const SPEEDS = [
  { label: '0.5×', value: '0.5' },
  { label: '1×', value: '1' },
  { label: '2×', value: '2' },
  { label: '5×', value: '5' },
  { label: 'Max', value: '0' },
];

const STATUS_COLOR: Record<string, string> = { running: 'green', paused: 'gray', finished: 'blue', error: 'red' };

export function WorldControls({ world, connected, onUpdate, onError }: Props) {
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<WorldView>) => {
    setBusy(true);
    try {
      onUpdate(await fn());
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const running = world.status === 'running';
  return (
    <Group gap="xs" wrap="wrap">
      <Badge color={STATUS_COLOR[world.status] ?? 'gray'} variant="light">{world.status}</Badge>
      <Text size="sm" fw={600} ff="monospace">{world.time}</Text>
      <Text size="xs" c="dimmed">tick {world.tick}</Text>
      {running ? (
        <Button size="xs" color="orange" loading={busy} onClick={() => run(() => api.pause(world.id))}>Pause</Button>
      ) : (
        <Button size="xs" disabled={world.status === 'finished'} loading={busy} onClick={() => run(() => api.start(world.id))}>
          {world.status === 'error' ? 'Resume' : 'Run'}
        </Button>
      )}
      <Button size="xs" variant="default" disabled={running || busy || world.status === 'finished'} onClick={() => run(() => api.step(world.id, 1))}>
        Step
      </Button>
      <Button size="xs" variant="default" disabled={running || busy || world.status === 'finished'} onClick={() => run(() => api.step(world.id, world.ticks_per_day))}>
        +1 day
      </Button>
      <SegmentedControl size="xs" data={SPEEDS} value={String(world.speed)}
        onChange={(v) => run(() => api.speed(world.id, Number(v)))} aria-label="Ticks per second" />
      <Tooltip label={connected ? 'Live updates connected' : 'Reconnecting to live updates…'}>
        <ActionIcon variant="transparent" size="sm" aria-label="connection status">
          <span style={{ width: 8, height: 8, borderRadius: 4, background: connected ? '#40c057' : '#fa5252', display: 'inline-block' }} />
        </ActionIcon>
      </Tooltip>
      {world.last_error && <Text size="xs" c="red">{world.last_error}</Text>}
    </Group>
  );
}
