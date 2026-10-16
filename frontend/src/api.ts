// Thin typed client for the backend REST API. The browser never talks to an
// LLM provider; all model calls happen server-side.
import type { AgentDetail, Decision, Message, Metrics, Preset, SimEvent, WorldSummary, WorldView } from './types';

const TOKEN_KEY = 'aisim.apiToken';

function authHeaders(): Record<string, string> {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export function setApiToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token only lives for this request cycle */
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<{ status: string; anthropic_key_configured: boolean; database: string }>('/api/health'),
  presets: () => request<Preset[]>('/api/presets'),
  preset: (id: string) => request<Record<string, any>>(`/api/presets/${id}`),
  worlds: () => request<WorldSummary[]>('/api/worlds'),
  createWorld: (body: { preset: string; name?: string; overrides?: Record<string, unknown>; start?: boolean }) =>
    post<WorldView>('/api/worlds', body),
  world: (id: string) => request<WorldView>(`/api/worlds/${id}`),
  worldConfig: (id: string) => request<Record<string, any>>(`/api/worlds/${id}/config`),
  deleteWorld: (id: string) => request<void>(`/api/worlds/${id}`, { method: 'DELETE' }),
  start: (id: string) => post<WorldView>(`/api/worlds/${id}/start`),
  pause: (id: string) => post<WorldView>(`/api/worlds/${id}/pause`),
  step: (id: string, count = 1) => post<WorldView>(`/api/worlds/${id}/step`, { count }),
  speed: (id: string, speed: number) => post<WorldView>(`/api/worlds/${id}/speed`, { speed }),
  agent: (id: string, agentId: string) => request<AgentDetail>(`/api/worlds/${id}/agents/${agentId}`),
  events: (id: string, params: Record<string, string | number | boolean> = {}) =>
    request<SimEvent[]>(`/api/worlds/${id}/events?${new URLSearchParams(params as any)}`),
  messages: (id: string, agent?: string) =>
    request<Message[]>(`/api/worlds/${id}/messages${agent ? `?agent=${agent}` : ''}`),
  decisions: (id: string, agent?: string, limit = 100) =>
    request<Decision[]>(`/api/worlds/${id}/decisions?limit=${limit}${agent ? `&agent=${agent}` : ''}`),
  relationships: (id: string) => request<{ agent_id: string; other_id: string; trust: number; familiarity: number; affinity: number }[]>(
    `/api/worlds/${id}/relationships`),
  trustChanges: (id: string, agent?: string) =>
    request<{ tick: number; agent_id: string; other_id: string; reason: string; positive: boolean; trust_before: number; trust_after: number }[]>(
      `/api/worlds/${id}/trust${agent ? `?agent=${agent}` : ''}`),
  metrics: (id: string, every = 1) => request<Metrics[]>(`/api/worlds/${id}/metrics?every=${every}`),
  llm: (id: string) => request<{ live: Record<string, any>; summary: Record<string, any>; recent: any[] }>(
    `/api/worlds/${id}/llm`),
};

export function wsUrl(worldId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws/worlds/${worldId}`;
}
