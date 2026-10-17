// Shapes of the backend's JSON views (see backend/aisim/runtime/views.py).

export interface Location {
  id: string;
  name: string;
  type: 'workplace' | 'food' | 'rest' | 'gathering' | 'wild';
  x: number;
  y: number;
  radius: number;
  capacity: number | null;
  stock: number | null;
  max_stock: number | null;
  price: number | null;
  occupancy: number;
}

export interface AgentBrief {
  id: string;
  name: string;
  x: number;
  y: number;
  alive: boolean;
  controller: 'rule' | 'llm';
  action: string;
  traveling: boolean;
  intention: string | null;
  mood: string;
  health: number;
  energy: number;
  hunger: number;
  tokens: number;
  food: number;
  existential_active: boolean;
  said: string | null;
  /** Recipient of what the agent said this tick. */
  said_to?: string | null;
  /** Character sprite sheet (see backend/aisim/runtime/appearance.py). */
  sprite?: string;
}

export interface LLMStats {
  provider: string;
  model?: string;
  requests?: number;
  failures?: number;
  timeouts?: number;
  spend_usd?: number;
  budget_exhausted?: boolean;
  queue_depth?: number;
  [key: string]: unknown;
}

export interface WorldView {
  id: string;
  name: string;
  tick: number;
  time: string;
  day: number;
  ticks_per_day: number;
  status: 'paused' | 'running' | 'finished' | 'error';
  speed: number;
  width: number;
  height: number;
  locations: Location[];
  agents: AgentBrief[];
  llm?: LLMStats;
  last_error?: string | null;
  last_tick_seconds?: number;
  max_ticks?: number | null;
  metrics?: Metrics | null;
  preset?: string | null;
}

export interface SimEvent {
  id?: number;
  tick: number;
  type: string;
  summary: string;
  agent_id: string | null;
  target_id: string | null;
  visibility: string;
  participants: string[];
  data: Record<string, unknown>;
  importance: number;
}

export interface Message {
  id: string;
  sender_id: string;
  sender_name?: string;
  recipient_id: string;
  content: string;
  tokens: number;
  sent_tick: number;
  token_cost: number;
  existential: boolean;
}

export interface Decision {
  tick: number;
  agent_id: string;
  source: string;
  valid: boolean;
  reason: string | null;
  applied_action: string | null;
  visible_intention: string | null;
  existential_active: boolean;
  fallback_reason: string | null;
  latency_ms: number | null;
  proposal: Record<string, unknown>;
  notes: string[];
}

export type Metrics = {
  tick: number;
  day: number;
  population: number;
  alive: number;
  deaths_total: number;
  deaths_by_cause: Record<string, number>;
  tokens_mean: number;
  tokens_gini: number;
  hunger_mean: number;
  energy_mean: number;
  health_mean: number;
  happiness_mean: number;
  stress_mean: number;
  loneliness_mean: number;
  trust_mean: number;
  actions: Record<string, number>;
  messages_sent: number;
  trades: number;
  gifts: number;
  help_given: number;
  refusals: number;
  thefts: number;
  existential_activations: number;
  existential_reflections: number;
  existential_messages: number;
  food_stock_total: number;
  llm_spend_usd?: number;
  [key: string]: unknown;
};

export interface TickPayload {
  type: 'tick';
  world: WorldView;
  metrics: Metrics;
  events: SimEvent[];
  messages: Message[];
  decisions: Decision[];
}

export interface Relationship {
  other_id: string;
  other_name: string;
  trust: number;
  trust_alpha: number;
  trust_beta: number;
  familiarity: number;
  affinity: number;
  interactions: Record<string, number>;
  other_alive: boolean;
}

export interface Memory {
  id: string;
  tick: number;
  kind: string;
  content: string;
  importance: number;
  related_agents: string[];
  tags: string[];
  source: string;
}

export interface AgentDetail {
  id: string;
  name: string;
  background: string;
  controller: string;
  alive: boolean;
  personality: Record<string, number>;
  initial_personality?: Record<string, number>;
  sprite?: string;
  trait_descriptions: Record<string, string>;
  tokens: number;
  food: number;
  energy: number;
  health: number;
  hunger: number;
  knowledge: number;
  artworks: number;
  emotions: Record<string, number>;
  current_mood: string;
  current_action: string;
  visible_intention: string | null;
  goals: { id: string; label: string; salience: number; active: boolean }[];
  active_intentions: string[];
  attention_capacity: number;
  communication_capacity: number;
  work_capacity: number;
  work_ticks_today: number;
  relationships: Relationship[];
  memories: Memory[];
  short_term: { tick: number; kind: string; text: string }[];
  life_summary: string[];
  time_allocation: Record<string, number>;
  stats: Record<string, number>;
  existential: {
    activations: number;
    opportunities: number;
    ticks_contemplating: number;
    conversations: number;
    reflections: number;
    last_probability: number;
    novelty: number;
    discussion_exposure: number;
    uncertainty: number;
    beliefs: { tick: number; text: string }[];
  };
  death: { tick: number; time: string; cause: string; last_actions: string[] } | null;
  decisions: Decision[];
  trait_history: { tick: number; trait: string; old: number; new: number }[];
  pending_offers: { id: string; from_name: string; to_id: string; offer: object; request: object }[];
  last_failure: string | null;
  memory_archive_count: number;
}

export interface WorldSummary {
  id: string;
  name: string;
  preset: string | null;
  status: string;
  tick: number;
  seed: number;
  alive?: number;
  population?: number;
  llm_spend_usd: number;
  created_at: string;
  experiment_id?: string | null;
  condition?: string | null;
}

export interface Preset {
  id: string;
  name: string;
  description: string;
}

/** A detected conversation (backend analysis/conversations.py). */
export interface ConversationThread {
  id: string;
  participants: string[];
  names: string[];
  first_tick: number;
  last_tick: number;
  time: string;
  last_time: string;
  message_count: number;
  messages_by_sender: Record<string, number>;
  group: boolean;
  existential: boolean;
  last_message: { id: string; sender_id: string; recipient_id: string; content: string; sent_tick: number };
}

export type MessageStatus = 'read' | 'sending' | 'unread' | 'undelivered' | 'never_read';

export interface ConversationMessage {
  id: string;
  sender_id: string;
  recipient_id: string;
  sender_name: string;
  recipient_name: string;
  content: string;
  tokens: number;
  token_cost: number;
  sent_tick: number;
  deliver_tick: number;
  read_tick: number | null;
  read_time: string | null;
  time: string;
  status: MessageStatus;
  existential: boolean;
  /** The sender's visible intention when it sent the message. */
  intention: string | null;
}

export interface ConversationDetail {
  participants: { id: string; name: string; alive: boolean; controller: string; sprite: string }[];
  messages: ConversationMessage[];
  events: (SimEvent & { time: string })[];
  tick: number;
}
