const BASE = "/api/v1";

async function req(path: string, opts: RequestInit = {}) {
  const r = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const d = await r.json();
      msg = d.detail || d.error || msg;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  get: (p: string) => req(p),
  post: (p: string, body?: unknown) => req(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  del: (p: string) => req(p, { method: "DELETE" }),

  // config
  getConfig: () => req("/config"),
  saveConfig: (b: unknown) => req("/config", { method: "POST", body: JSON.stringify(b) }),

  // settings
  getSettings: () => req("/settings"),
  saveSettings: (b: unknown) => req("/settings", { method: "POST", body: JSON.stringify(b) }),

  // kline / market
  getKline: (symbol: string, tf = "15m", limit = 100) => req(`/kline/${symbol}/${tf}?limit=${limit}`),
  getSymbols: () => req("/kline/symbols"),

  // strategy
  listStrategies: () => req("/strategy/list"),
  getSignal: (symbol: string, sid: string) => req(`/strategy/signal/${symbol}?strategy_id=${sid}`),
  getIndicators: (symbol: string, tf = "15m") => req(`/strategy/indicators/${symbol}?timeframe=${tf}`),
  activateStrategy: (symbol: string, sid: string) => req(`/strategy/activate?symbol=${symbol}&strategy_id=${sid}`, { method: "POST" }),
  listCustom: () => req("/strategy/custom/list"),
  createCustom: (b: unknown) => req("/strategy/custom/create", { method: "POST", body: JSON.stringify(b) }),
  deleteCustom: (id: string) => req(`/strategy/custom/${id}`, { method: "DELETE" }),

  // AI
  getTrend: (symbol: string) => req(`/ai/trend/${symbol}`),
  getReports: (symbol = "", limit = 50) => req(`/ai/reports?symbol=${symbol}&limit=${limit}`),
  senseNow: () => req("/ai/sense-now", { method: "POST" }),
  getSchedule: () => req("/ai/schedule"),
  setSchedule: (enabled: boolean, minutes: number) => req(`/ai/schedule?enabled=${enabled}&minutes=${minutes}`, { method: "POST" }),
  getNews: (limit = 20, force = false) => req(`/ai/news?limit=${limit}&force=${force}`),
  chat: (b: unknown) => req("/ai/chat", { method: "POST", body: JSON.stringify(b) }),
  applyAction: (action: unknown) => req("/ai/chat/apply-action", { method: "POST", body: JSON.stringify(action) }),

  // risk
  getRisk: () => req("/risk/status"),
  resetRisk: () => req("/risk/reset", { method: "POST" }),

  // trade
  placeOrder: (b: unknown) => req("/trade/order", { method: "POST", body: JSON.stringify(b) }),
  strategyOrder: (symbol: string, sid: string, leverage?: number) =>
    req(`/trade/strategy-order?symbol=${symbol}&strategy_id=${sid}${leverage ? `&leverage=${leverage}` : ""}`, { method: "POST" }),
  getPositions: (symbol = "") => req(`/trade/positions?symbol=${symbol}`),
  closePosition: (id: number) => req(`/trade/close/${id}`, { method: "POST" }),
  emergencyClose: (symbol: string) => req(`/trade/emergency-close?symbol=${symbol}`, { method: "POST" }),
  getAccount: () => req("/trade/account"),
  getTradeHistory: (symbol = "", limit = 100) => req(`/trade/history?symbol=${symbol}&limit=${limit}`),

  // scheduler
  schedulerStatus: (symbol: string) => req(`/scheduler/status/${symbol}`),
  confirmSwitch: (symbol: string) => req(`/scheduler/confirm/${symbol}`, { method: "POST" }),
  rejectSwitch: (symbol: string) => req(`/scheduler/reject/${symbol}`, { method: "POST" }),

  // backtest
  runBacktest: (b: unknown) => req("/backtest/run", { method: "POST", body: JSON.stringify(b) }),
  cancelBacktest: (id: string) => req(`/backtest/${id}/cancel`, { method: "POST" }),

  // autopilot
  autopilotStart: (symbols = "") => req(`/autopilot/start?symbols=${encodeURIComponent(symbols)}`, { method: "POST" }),
  autopilotStop: () => req("/autopilot/stop", { method: "POST" }),
  autopilotStatus: () => req("/autopilot/status"),
  autopilotHistory: (limit = 50) => req(`/autopilot/history?limit=${limit}`),
  autopilotAccount: () => req("/autopilot/account"),
};
