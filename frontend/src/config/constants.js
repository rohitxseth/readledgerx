export const API_BASE = "http://localhost:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");
export const WS_URL = `${WS_BASE}/chat/ws`;

export const RECONNECT_BASE_DELAY = 1000;
export const RECONNECT_MAX_DELAY = 30000;
export const PING_INTERVAL = 25000;

export const DEFAULT_SUGGESTIONS = [
  "Search for a book",
  "Show my progress",
  "Help",
];
