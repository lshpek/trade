import type {
  AiSignalsResponse,
  AuditLogItem,
  BacktestRequest,
  BacktestResult,
  Dashboard,
  ExecuteSignalResponse,
  IntegrationStatus,
  PaperOrder,
  PaperPortfolio,
  PaperRiskSettings,
  SessionItem,
  SystemEvent,
} from './types';

declare global {
  interface Window { Telegram?: { WebApp?: { initData?: string; ready?: () => void; expand?: () => void; colorScheme?: string } } }
}

export interface IdentityUser {
  id?: string;
  login: string;
  role?: string;
  roles: string[];
  permissions: string[];
  must_change_password: boolean;
  status?: string;
  trading_access?: 'read' | 'paper' | 'disabled';
  expires_at?: string | null;
}
export interface AuthMe { authenticated: boolean; user: IdentityUser | null }
export interface ManagedUser extends IdentityUser {
  id: string; created_at: string; updated_at: string; last_login_at: string | null; created_by: string | null;
}
export interface UsersPage { items: ManagedUser[]; total: number; limit: number; offset: number }

function cookieValue(name: string): string {
  const prefix = `${name}=`;
  const found = document.cookie.split('; ').find(part => part.startsWith(prefix));
  return found ? decodeURIComponent(found.slice(prefix.length)) : '';
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const initData = window.Telegram?.WebApp?.initData ?? '';
  if (initData) headers.set('X-Telegram-Init-Data', initData);
  const method = (options.method ?? 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = cookieValue('botvex_csrf');
    if (csrf) headers.set('X-CSRF-Token', csrf);
  }
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  if (!response.ok) {
    if (response.status === 401 && !path.endsWith('/auth/login') && !path.endsWith('/auth/me') && !path.endsWith('/auth/telegram/exchange')) {
      window.dispatchEvent(new Event('botvex:unauthorized'));
    }
    let message = `Ошибка сервера (${response.status}).`;
    try {
      const payload = await response.json() as { detail?: string | Array<{ msg?: string }> };
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (Array.isArray(payload.detail)) message = payload.detail.map(item => item.msg).filter(Boolean).join('; ') || message;
    } catch { /* Keep generic error. */ }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getMe = () => request<AuthMe>('/api/v1/auth/me');
export const login = (loginName: string, password: string) => request<{ authenticated: boolean; login: string; roles: string[]; must_change_password: boolean }>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ login: loginName, password }) });
export const logout = () => request<{ authenticated: boolean }>('/api/v1/auth/logout', { method: 'POST' });
export const changePassword = (current_password: string, new_password: string) => request<{ password_changed: boolean; reauthentication_required: boolean }>('/api/v1/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: current_password || undefined, new_password }) });
export const activateAccount = (token: string, password: string) => request<{ activated: boolean; login: string; status: string }>('/api/v1/auth/activate', { method: 'POST', body: JSON.stringify({ token, password }) });
export const resetPassword = (token: string, password: string) => request<{ password_reset: boolean; login: string; status: string }>('/api/v1/auth/reset-password', { method: 'POST', body: JSON.stringify({ token, password }) });
export const getSessions = () => request<SessionItem[]>('/api/v1/auth/sessions');
export const revokeSession = (id: string) => request<{ revoked: boolean }>(`/api/v1/auth/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const getDashboard = () => request<Dashboard>('/api/v1/dashboard');
export const getStatus = () => request<IntegrationStatus[]>('/api/v1/system/status');
export const getEvents = () => request<SystemEvent[]>('/api/v1/events');
export const getPaperPortfolio = () => request<PaperPortfolio>('/api/v1/paper/portfolio');
export const getPaperOrders = () => request<PaperOrder[]>('/api/v1/paper/orders');
export const createPaperOrder = (body: { symbol: string; side: 'BUY' | 'SELL'; quantity: number; reference_price: number; idempotency_key: string }) => request<PaperOrder>('/api/v1/paper/orders', { method: 'POST', body: JSON.stringify(body) });
export const getPaperRiskSettings = () => request<PaperRiskSettings>('/api/v1/paper/risk-settings');
export const savePaperRiskSettings = (body: Omit<PaperRiskSettings, 'live_trading_allowed'>) => request<PaperRiskSettings>('/api/v1/paper/risk-settings', { method: 'PUT', body: JSON.stringify(body) });

export const getAiSignals = (symbols?: string) => request<AiSignalsResponse>(`/api/v1/ai/signals${symbols ? `?symbols=${encodeURIComponent(symbols)}` : ''}`);
export const executeAiSignal = (body: { mode: 'single' | 'auto_top'; symbol?: string; max_orders?: number; idempotency_prefix?: string }) => request<ExecuteSignalResponse>('/api/v1/ai/execute-signal', { method: 'POST', body: JSON.stringify(body) });
export const runBacktest = (body: BacktestRequest) => request<BacktestResult>('/api/v1/backtests/run', { method: 'POST', body: JSON.stringify(body) });
export const getBacktests = (limit = 15) => request<BacktestResult[]>(`/api/v1/backtests?limit=${limit}`);

export const getUsers = (search = '') => request<UsersPage>(`/api/v1/admin/users?limit=100&search=${encodeURIComponent(search)}`);
export const createUser = (body: { login: string; role: string; trading_access: string; expiration: string }) => request<{ user: ManagedUser; activation_status: string; activation_required: boolean; message: string }>('/api/v1/admin/users', { method: 'POST', body: JSON.stringify(body) });
export const issueActivationLink = (id: string) => request<{ activation_url: string; expires_in_seconds: number; warning: string }>(`/api/v1/admin/users/${encodeURIComponent(id)}/activation-link`, { method: 'POST' });
export const issueResetPasswordLink = (id: string) => request<{ reset_url: string; expires_in_seconds: number; warning: string }>(`/api/v1/admin/users/${encodeURIComponent(id)}/reset-password`, { method: 'POST' });
export const assignOwnerRole = (id: string, confirm_login: string) => request<ManagedUser>(`/api/v1/admin/users/${encodeURIComponent(id)}/assign-owner`, { method: 'POST', body: JSON.stringify({ confirm_login }) });
export const getAuditLogs = (limit = 50) => request<AuditLogItem[]>(`/api/v1/admin/audit-logs?limit=${limit}`);
export const disableUser = (id: string) => request<ManagedUser>(`/api/v1/admin/users/${encodeURIComponent(id)}/disable`, { method: 'POST' });
export const reactivateUser = (id: string) => request<ManagedUser>(`/api/v1/admin/users/${encodeURIComponent(id)}/reactivate`, { method: 'POST' });

export const linkTelegramAccount = () => request<{ linked: boolean; telegram_user_id: number }>('/api/v1/auth/telegram/link', { method: 'POST' });
export const exchangeTelegramAccount = () => request<{ authenticated: boolean; login: string; roles: string[]; must_change_password: boolean }>('/api/v1/auth/telegram/exchange', { method: 'POST' });
export const revokeUserSessions = (id: string) => request<{ revoked: boolean }>(`/api/v1/admin/users/${encodeURIComponent(id)}/revoke-sessions`, { method: 'POST' });
export const updateUser = (id: string, body: { role?: string; trading_access?: string; status?: string; expiration?: string }) => request<ManagedUser>(`/api/v1/admin/users/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) });
