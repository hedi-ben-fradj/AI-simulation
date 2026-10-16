import { useEffect, useState } from 'react';
import { Alert, Button, Group, Modal, NumberInput, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { api } from '../api';
import type { Preset, WorldView } from '../types';

interface Props {
  opened: boolean;
  onClose: () => void;
  onCreated: (w: WorldView) => void;
}

export function CreateWorldModal({ opened, onClose, onCreated }: Props) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState('default');
  const [name, setName] = useState('');
  const [population, setPopulation] = useState<number | string>(5);
  const [seed, setSeed] = useState<number | string>(42);
  const [provider, setProvider] = useState<string>('preset');
  const [llmAgents, setLlmAgents] = useState<number | string>('');
  const [model, setModel] = useState('');
  const [spend, setSpend] = useState<number | string>('');
  const [start, setStart] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keyConfigured, setKeyConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    if (!opened) return;
    api.presets().then(setPresets).catch((e) => setError(String(e)));
    api.health().then((h) => setKeyConfigured(h.anthropic_key_configured)).catch(() => setKeyConfigured(null));
  }, [opened]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const overrides: Record<string, any> = { simulation: { population: Number(population), random_seed: Number(seed) } };
    const llm: Record<string, unknown> = {};
    if (provider !== 'preset') llm.provider = provider;
    if (llmAgents !== '') llm.llm_agents = Number(llmAgents);
    if (model.trim()) llm.model = model.trim();
    if (spend !== '') llm.maximum_world_spend = Number(spend);
    if (Object.keys(llm).length) overrides.llm = llm;
    try {
      const w = await api.createWorld({ preset, name: name || undefined, overrides, start });
      onCreated(w);
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const current = presets.find((p) => p.id === preset);
  return (
    <Modal opened={opened} onClose={onClose} title="New world" size="lg">
      <Stack gap="sm">
        <Select
          label="Environment preset"
          data={presets.map((p) => ({ value: p.id, label: p.name }))}
          value={preset}
          onChange={(v) => v && setPreset(v)}
          allowDeselect={false}
        />
        {current?.description && (
          <Text size="sm" c="dimmed">
            {current.description}
          </Text>
        )}
        <TextInput label="Name" placeholder={current?.name ?? 'World'} value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Group grow>
          <NumberInput label="Population" min={1} max={20} value={population} onChange={setPopulation} />
          <NumberInput label="Random seed" value={seed} onChange={setSeed} />
        </Group>
        <Select
          label="Agent decision provider"
          description="LLM calls happen only on the backend. 'mock' exercises the LLM pipeline offline at no cost."
          data={[
            { value: 'preset', label: 'As defined by preset' },
            { value: 'none', label: 'Rule-based agents only' },
            { value: 'mock', label: 'Mock LLM (offline)' },
            { value: 'anthropic', label: 'Anthropic Claude (API cost)' },
          ]}
          value={provider}
          onChange={(v) => v && setProvider(v)}
          allowDeselect={false}
        />
        {provider === 'anthropic' && keyConfigured === false && (
          <Alert color="yellow" title="No API key on the backend">
            ANTHROPIC_API_KEY is not set on the server. LLM requests will fail and agents will use the rule-based fallback.
          </Alert>
        )}
        <Group grow>
          <NumberInput label="LLM-controlled agents" placeholder="all" min={0} value={llmAgents} onChange={setLlmAgents} />
          <TextInput label="Model" placeholder="preset default" value={model} onChange={(e) => setModel(e.currentTarget.value)} />
          <NumberInput label="Max world spend (USD)" placeholder="preset" min={0} decimalScale={2} value={spend} onChange={setSpend} />
        </Group>
        <Switch label="Start running immediately" checked={start} onChange={(e) => setStart(e.currentTarget.checked)} />
        {error && (
          <Alert color="red" title="Could not create world">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} loading={busy}>
            Create world
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
