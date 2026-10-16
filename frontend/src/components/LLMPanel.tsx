import { useEffect, useState } from 'react';
import { Badge, Card, Group, SimpleGrid, Table, Text } from '@mantine/core';
import { api } from '../api';

interface Props {
  worldId: string;
  tick: number;
  agentNames: Record<string, string>;
}

// Real infrastructure cost (API usage), tracked separately from in-world communication cost.
export function LLMPanel({ worldId, tick, agentNames }: Props) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.llm>> | null>(null);
  useEffect(() => {
    const t = setTimeout(() => api.llm(worldId).then(setData).catch(() => undefined), 300);
    return () => clearTimeout(t);
  }, [worldId, Math.floor(tick / 3)]);

  if (!data) return <Text size="sm" c="dimmed">Loading…</Text>;
  const { live, summary, recent } = data;
  if (live.provider === 'none') {
    return <Text size="sm" c="dimmed">This world uses rule-based agents only; no LLM requests are made.</Text>;
  }
  const stat = (label: string, value: string) => (
    <Card withBorder padding="xs">
      <Text size="xs" c="dimmed">{label}</Text>
      <Text fw={700}>{value}</Text>
    </Card>
  );
  return (
    <>
      <Group gap="xs" mb="sm">
        <Badge variant="light">{live.provider}</Badge>
        {live.model && <Badge variant="outline">{live.model}</Badge>}
        {live.budget_exhausted && <Badge color="red">budget exhausted — agents on rule fallback</Badge>}
      </Group>
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="xs" mb="sm">
        {stat('Requests', String(summary.requests))}
        {stat('Failures', String(summary.failures))}
        {stat('Spend (USD)', `$${Number(summary.cost_usd).toFixed(4)}${live.max_world_spend != null ? ` / $${live.max_world_spend}` : ''}`)}
        {stat('Mean latency', `${Math.round(summary.mean_latency_ms)} ms`)}
        {stat('Input tokens', String(summary.input_tokens))}
        {stat('Output tokens', String(summary.output_tokens))}
        {stat('Timeouts (live)', String(live.timeouts ?? 0))}
        {stat('Queue depth', String(live.queue_depth ?? 0))}
      </SimpleGrid>
      {Object.keys(summary.errors ?? {}).length > 0 && (
        <Card withBorder padding="xs" mb="sm">
          <Text size="sm" fw={600}>Errors</Text>
          {Object.entries(summary.errors).map(([e, n]) => <Text key={e} size="xs">{String(n)} × {e}</Text>)}
        </Card>
      )}
      <Table fz="xs" striped withTableBorder>
        <Table.Thead>
          <Table.Tr><Table.Th>Tick</Table.Th><Table.Th>Agent</Table.Th><Table.Th>In/Out tokens</Table.Th><Table.Th>Cost</Table.Th><Table.Th>Latency</Table.Th><Table.Th>Result</Table.Th></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {recent.slice().reverse().slice(0, 40).map((r, i) => (
            <Table.Tr key={i}>
              <Table.Td>{r.tick}</Table.Td>
              <Table.Td>{agentNames[r.agent_id] ?? r.agent_id}</Table.Td>
              <Table.Td>{r.input_tokens}/{r.output_tokens}</Table.Td>
              <Table.Td>${Number(r.cost_usd).toFixed(5)}</Table.Td>
              <Table.Td>{Math.round(r.latency_ms)} ms</Table.Td>
              <Table.Td c={r.success ? undefined : 'red'}>{r.success ? 'ok' : r.error}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </>
  );
}
