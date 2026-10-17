import { useCallback, useEffect, useRef, useState } from 'react';
import { api, wsUrl } from '../api';
import type { Message, Metrics, SimEvent, TickPayload, WorldView } from '../types';

const MAX_EVENTS = 500;
const MAX_MESSAGES = 300;
const MAX_METRICS = 20000;

export interface WorldStream {
  world: WorldView | null;
  metrics: Metrics[];
  events: SimEvent[];
  messages: Message[];
  connected: boolean;
  lastTickAt: number;
  /** Increases whenever a day's chronicle is written or rewritten. */
  chronicleVersion: number;
  error: string | null;
  refresh: () => Promise<void>;
  setWorld: (w: WorldView) => void;
}

// Subscribes to a world's live WebSocket stream and keeps a bounded history
// of metrics, events and messages for the UI. Reconnects with backoff.
export function useWorldStream(worldId: string | null): WorldStream {
  const [world, setWorld] = useState<WorldView | null>(null);
  const [metrics, setMetrics] = useState<Metrics[]>([]);
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastTickAt, setLastTickAt] = useState(0);
  const [chronicleVersion, setChronicleVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    if (!worldId) return;
    try {
      const [w, m, ev, msgs] = await Promise.all([
        api.world(worldId),
        api.metrics(worldId),
        api.events(worldId, { limit: 300 }),
        api.messages(worldId),
      ]);
      setWorld(w);
      setMetrics(m);
      setEvents(ev);
      const names = Object.fromEntries(w.agents.map((a) => [a.id, a.name]));
      setMessages(msgs.map((x) => ({ ...x, sender_name: names[x.sender_id] ?? x.sender_id })));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [worldId]);

  useEffect(() => {
    setWorld(null);
    setMetrics([]);
    setEvents([]);
    setMessages([]);
    if (!worldId) return;
    void refresh();
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const ws = new WebSocket(wsUrl(worldId));
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.type === 'tick') {
          const p = data as TickPayload;
          setWorld(p.world);
          setLastTickAt(performance.now());
          setMetrics((prev) => {
            const next = prev.length && prev[prev.length - 1].tick >= p.metrics.tick ? prev.filter((m) => m.tick < p.metrics.tick) : prev;
            const out = [...next, p.metrics];
            return out.length > MAX_METRICS ? out.slice(-MAX_METRICS) : out;
          });
          if (p.events.length) setEvents((prev) => [...prev, ...p.events].slice(-MAX_EVENTS));
          if (p.messages.length) setMessages((prev) => [...prev, ...p.messages].slice(-MAX_MESSAGES));
        } else if (data.type === 'chronicle') {
          setChronicleVersion((v) => v + 1);
        } else if (data.type === 'snapshot' || data.type === 'status') {
          setWorld((prev) => ({ ...(prev ?? {}), ...data.world }));
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
        retry += 1;
        timer = setTimeout(connect, Math.min(10000, 500 * 2 ** retry));
      };
      ws.onerror = () => ws.close();
    };
    connect();
    const ping = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send('ping');
    }, 25000);
    return () => {
      closed = true;
      clearInterval(ping);
      if (timer) clearTimeout(timer);
      wsRef.current?.close();
    };
  }, [worldId, refresh]);

  return { world, metrics, events, messages, connected, lastTickAt, chronicleVersion, error, refresh, setWorld };
}
