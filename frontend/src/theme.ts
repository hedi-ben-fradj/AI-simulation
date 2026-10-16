// Shared colour assignments for the map and charts.
export const LOCATION_COLORS: Record<string, number> = {
  workplace: 0xd4a72c,
  food: 0x4caf50,
  rest: 0x5c7cfa,
  gathering: 0xe64980,
  wild: 0x868e96,
};

export const LOCATION_ICONS: Record<string, string> = {
  workplace: '⚒',
  food: '🍞',
  rest: '☾',
  gathering: '✦',
  wild: '·',
};

export const MOOD_COLORS: Record<string, number> = {
  content: 0x40c057,
  calm: 0x20c997,
  curious: 0x22b8cf,
  contemplative: 0x9775fa,
  lonely: 0x4dabf7,
  stressed: 0xfd7e14,
  frustrated: 0xff922b,
  exhausted: 0xbe4bdb,
  starving: 0xfa5252,
  neutral: 0xadb5bd,
  dead: 0x495057,
};

export const hex = (n: number) => `#${n.toString(16).padStart(6, '0')}`;

// Categorical series colours, fixed order (validated CVD-safe adjacent order;
// light and dark steps). Assign by entity, never cycle past 8.
export const SERIES_LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
export const SERIES_DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];

export const ACTION_COLORS: Record<string, string> = {
  work: '#f59f00',
  eat: '#40c057',
  buy_food: '#69db7c',
  rest: '#5c7cfa',
  travel: '#adb5bd',
  socialize: '#e64980',
  talk: '#f783ac',
  explore: '#15aabf',
  reflect: '#9775fa',
  create: '#d6336c',
  study: '#1c7ed6',
  give: '#2f9e44',
  offer_trade: '#66a80f',
  accept_trade: '#5c940d',
  reject_trade: '#e8590c',
  steal: '#c92a2a',
  idle: '#ced4da',
  move: '#adb5bd',
};
