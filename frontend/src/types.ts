export type IntegrationState = 'connected' | 'unavailable' | 'degraded' | 'error';
export interface IntegrationStatus {
  name: string;
  state: IntegrationState;
  detail: string;
  checked_at: string;
}
export interface Dashboard {
  mode: 'DEMO' | 'PAPER';
  live_enabled: boolean;
  portfolio_available: boolean;
  balance: number | null;
  equity: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  as_of: string;
  message: string;
  integrations: IntegrationStatus[];
}
export interface SystemEvent {
  id: string;
  level: 'info' | 'warning' | 'error';
  title: string;
  detail: string;
  created_at: string;
}

export interface PaperPosition { symbol: string; quantity: number; average_price: number }
export interface PaperPortfolio {
  mode: 'PAPER'; live_enabled: false; simulated: true; initial_cash: number; cash: number;
  position_cost_basis: number; equity_at_cost_basis: number; positions: PaperPosition[];
  price_data_available: false; message: string;
}
export interface PaperOrder {
  id: string; symbol: string; side: 'BUY' | 'SELL'; quantity: number; reference_price: number;
  notional: number; fee: number; realized_pnl?: number; status: string; created_at: string; simulated: true;
  idempotent_replay?: boolean; price_source?: string;
}
export interface PaperRiskSettings {
  max_order_notional: number; max_position_notional: number; daily_loss_limit: number;
  kill_switch: boolean; live_trading_allowed: false;
}

export interface QuantFactor {
  name: string;
  impact: number;
  detail: string;
}

export interface QuantIndicators {
  ema9: number;
  ema21: number;
  ema50: number;
  rsi14: number;
  macd_hist: number;
  atr14: number;
  atr_pct: number;
  adx14: number;
  vwap20: number;
  zscore20: number;
}

export interface QuantSignal {
  symbol: string;
  regime: 'TREND_BULL' | 'TREND_BEAR' | 'MEAN_REVERTING' | 'HIGH_VOL_CHOP';
  action: 'BUY' | 'SELL' | 'HOLD';
  score: number;
  confidence: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  risk_reward: number;
  recommended_qty: number;
  order_notional: number;
  indicators: QuantIndicators;
  factors: QuantFactor[];
  risk_gate_passed: boolean;
  risk_gate_reason: string;
  thesis: string;
  engine_source: string;
}

export interface AiSignalsResponse {
  mode: 'PAPER';
  live_enabled: false;
  engine: string;
  generated_at: string;
  account_cash: number;
  kill_switch: boolean;
  signals: QuantSignal[];
}

export interface ExecuteSignalResponse {
  executed_count: number;
  orders: PaperOrder[];
  skipped: Array<{ symbol: string; reason: string }>;
  portfolio: PaperPortfolio;
}

export interface BacktestRequest {
  symbol: string;
  strategy: 'ensemble_quant' | 'ema_trend_atr' | 'vwap_zscore_reversion';
  bars: number;
  initial_cash: number;
  fee_bps: number;
  slippage_bps: number;
}

export interface BacktestEquityPoint {
  timestamp: string;
  equity: number;
  benchmark: number;
  drawdown_pct: number;
}

export interface BacktestTrade {
  entry_time: string;
  exit_time: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  return_pct: number;
  reason: string;
}

export interface BacktestResult {
  id: string;
  symbol: string;
  strategy: 'ensemble_quant' | 'ema_trend_atr' | 'vwap_zscore_reversion';
  bars: number;
  initial_cash: number;
  final_equity: number;
  total_return_pct: number;
  benchmark_return_pct: number;
  alpha_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  expectancy_usd: number;
  total_trades: number;
  fee_bps: number;
  slippage_bps: number;
  equity_curve: BacktestEquityPoint[];
  trades: BacktestTrade[];
  created_at: string;
  simulated: true;
}

export interface SessionItem {
  id: string;
  created_at: number;
  expires_at: number;
  last_seen_at: number;
  revoked_at: number | null;
  user_agent: string | null;
  ip_address: string | null;
  active: boolean;
}

export interface AuditLogItem {
  id: string;
  actor_user_id: string | null;
  target_user_id: string | null;
  action: string;
  outcome: string;
  created_at: string;
  metadata: Record<string, unknown>;
}
