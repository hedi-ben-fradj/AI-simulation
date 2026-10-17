import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, Group, PasswordInput, SimpleGrid, Table, Text } from '@mantine/core';
import { api } from '../api';

const KEY_NAMES: Record<string, string> = { anthropic: 'ANTHROPIC_API_KEY', openrouter: 'OPENROUTER_API_KEY' };
const CREDENTIAL_LABELS: Record<string, string> = {
  world: 'key entered for this world', server: "server's key", subscription: 'Claude subscription (claude CLI)',
  missing: 'no API key',
};
// What to tell the researcher when every LLM call fails the same way.
const ERROR_HINTS: Record<string, string> = {
  authentication: 'The provider rejected the credentials. Check the API key (or, for the subscription, run `claude` and sign in).',
  missing_api_key: 'There is no API key for this world.',
  insufficient_credits: 'The provider account is out of credits (or the key reached its limit).',
  model_not_found: 'The provider does not know this model ID.',
  permission_denied: 'The provider refused the request for this key or model.',
  rate_limited: 'The provider is rate-limiting requests; some agents use the rule-based policy until it recovers.',
  cli_not_found: "The 'claude' command is not installed on the server (or AISIM_CLAUDE_PATH is wrong).",
  cli_unsupported_option: 'The installed Claude Code is too old for an option this app uses; update it (claude update).',
  timeout: 'Answers arrive too late for the tick; raise the wait per tick or slow the simulation down.',
};

function KeyForm({ worldId, provider, onSaved }: { worldId: string; provider: string; onSaved: () => void }) {
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.setCredentials(worldId, key.trim());
      setKey('');
      onSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Group align="flex-end" gap="xs" mt="xs">
      <PasswordInput label={KEY_NAMES[provider] ?? 'API key'} value={key} onChange={(e) => setKey(e.currentTarget.value)}
        autoComplete="off" style={{ flex: 1 }} error={error} />
      <Button onClick={save} loading={busy} disabled={!key.trim()}>Use this key</Button>
    </Group>
  );
}

interface Props {
  worldId: string;
  tick: number;
  agentNames: Record<string, string>;
}

// Real infrastructure cost (API usage), tracked separately from in-world communication cost.
export function LLMPanel({ worldId, tick, agentNames }: Props) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.llm>> | null>(null);
  const [changingKey, setChangingKey] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => api.llm(worldId).then(setData).catch(() => undefined), 300);
    return () => clearTimeout(t);
  }, [worldId, Math.floor(tick / 3), reload]);

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
        {live.credential && live.credential !== 'not_needed' && (
          <Badge variant="dot" color={live.credential === 'missing' ? 'red' : 'teal'}>{CREDENTIAL_LABELS[live.credential] ?? live.credential}</Badge>
        )}
        {live.budget_exhausted && <Badge color="red">budget exhausted — agents on rule fallback</Badge>}
        {KEY_NAMES[live.provider] && live.credential !== 'missing' && (
          <Button size="compact-xs" variant="subtle" onClick={() => setChangingKey((v) => !v)}>Change key</Button>
        )}
      </Group>
      {live.credential === 'missing' && (
        <Alert color="red" mb="sm" title="This world has no API key">
          <Text size="sm">
            Keys entered on the setup page are kept only in the server's memory, so they are gone after a restart
            (or the server has no {KEY_NAMES[live.provider]}). LLM agents use the rule-based policy until you enter a key.
          </Text>
          <KeyForm worldId={worldId} provider={live.provider} onSaved={() => setReload((n) => n + 1)} />
        </Alert>
      )}
      {changingKey && live.credential !== 'missing' && (
        <Card withBorder padding="xs" mb="sm">
          <KeyForm worldId={worldId} provider={live.provider} onSaved={() => { setChangingKey(false); setReload((n) => n + 1); }} />
        </Card>
      )}
      {live.last_error_kind && live.credential !== 'missing' && (
        <Alert color="orange" mb="sm" title={`Latest LLM call failed: ${String(live.last_error_kind).replace(/_/g, ' ')}`}>
          <Text size="sm">{ERROR_HINTS[live.last_error_kind] ?? 'Affected agents use the rule-based policy for that tick. Details are in the table below.'}</Text>
        </Alert>
      )}
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="xs" mb="sm">
        {stat('Requests', String(summary.requests))}
        {stat('Failures', String(summary.failures))}
        {live.provider === 'claude_code'
          ? stat('Spend', 'subscription')
          : stat('Spend (USD)', `$${Number(summary.cost_usd).toFixed(4)}${live.max_world_spend != null ? ` / $${live.max_world_spend}` : ''}`)}
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
