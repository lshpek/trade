import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BrainCircuit,
  ChartNoAxesCombined,
  CircleHelp,
  Clock3,
  Database,
  LayoutDashboard,
  LogOut,
  Play,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRoundCog,
  WalletCards,
  Zap,
} from 'lucide-react';
import {
  createPaperOrder,
  exchangeTelegramAccount,
  executeAiSignal,
  getAiSignals,
  getAuditLogs,
  getBacktests,
  getDashboard,
  getEvents,
  getMe,
  getPaperOrders,
  getPaperPortfolio,
  getPaperRiskSettings,
  getSessions,
  getStatus,
  linkTelegramAccount,
  logout,
  revokeSession,
  runBacktest,
  savePaperRiskSettings,
  type IdentityUser,
} from './api';
import { ActivationScreen, ChangePasswordScreen, LoginScreen } from './AuthScreens';
import UserManagement from './UserManagement';
import type {
  AiSignalsResponse,
  AuditLogItem,
  BacktestResult,
  Dashboard,
  IntegrationStatus,
  PaperOrder,
  PaperPortfolio,
  PaperRiskSettings,
  QuantSignal,
  SessionItem,
  SystemEvent,
} from './types';

type Tab = 'overview' | 'portfolio' | 'trades' | 'ai' | 'backtests' | 'events' | 'settings' | 'users';
const tabs: { id: Tab; label: string; icon: typeof LayoutDashboard }[] = [
  { id: 'overview', label: 'Обзор', icon: LayoutDashboard },
  { id: 'portfolio', label: 'Портфель', icon: WalletCards },
  { id: 'trades', label: 'Сделки', icon: ArrowUpRight },
  { id: 'ai', label: 'ИИ и стратегия', icon: BrainCircuit },
  { id: 'backtests', label: 'Бэктесты', icon: ChartNoAxesCombined },
  { id: 'events', label: 'События', icon: Activity },
  { id: 'settings', label: 'Настройки', icon: SlidersHorizontal },
  { id: 'users', label: 'Пользователи', icon: UserRoundCog },
];

function formatDate(value?: string) {
  if (!value) return 'Нет данных';
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}
function statusLabel(state: IntegrationStatus['state']) {
  return ({ connected: 'Работает', unavailable: 'Не подключено', degraded: 'Частично', error: 'Ошибка' })[state];
}
function regimeLabel(regime: QuantSignal['regime']) {
  return ({
    TREND_BULL: 'Бычий тренд',
    TREND_BEAR: 'Медвежий тренд',
    MEAN_REVERTING: 'Возврат к среднему',
    HIGH_VOL_CHOP: 'Высокая волатильность',
  })[regime];
}

function App() {
  const authInitStarted = useRef(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [authUser, setAuthUser] = useState<IdentityUser | null>(null);
  const activationToken = new URLSearchParams(window.location.search).get('token') ?? new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token');
  const routePath = window.location.pathname.replace(/\/$/, '');
  const activationMode = ['/activate', '/reset-password'].includes(routePath) && Boolean(activationToken);
  const activationKind = routePath === '/reset-password' ? 'reset' : 'activate';
  const [tab, setTab] = useState<Tab>('overview');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [status, setStatus] = useState<IntegrationStatus[]>([]);
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState('');
  const [paperPortfolio, setPaperPortfolio] = useState<PaperPortfolio | null>(null);
  const [paperOrders, setPaperOrders] = useState<PaperOrder[]>([]);
  const [riskSettings, setRiskSettings] = useState<PaperRiskSettings | null>(null);
  const [orderSymbol, setOrderSymbol] = useState('AAPL');
  const [orderSide, setOrderSide] = useState<'BUY' | 'SELL'>('BUY');
  const [orderQuantity, setOrderQuantity] = useState('1');
  const [orderPrice, setOrderPrice] = useState('100');
  const [actionMessage, setActionMessage] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  const pendingOrder = useRef<{ fingerprint: string; key: string } | null>(null);

  // Quant & AI Signals state
  const [aiScan, setAiScan] = useState<AiSignalsResponse | null>(null);
  const [aiCustomSymbols, setAiCustomSymbols] = useState('NVDA,AAPL,MSFT,SPY,BTC-USD,ETH-USD');
  const [aiLoading, setAiLoading] = useState(false);

  // Backtester state
  const [btSymbol, setBtSymbol] = useState('NVDA');
  const [btStrategy, setBtStrategy] = useState<'ensemble_quant' | 'ema_trend_atr' | 'vwap_zscore_reversion'>('ensemble_quant');
  const [btBars, setBtBars] = useState('240');
  const [btCash, setBtCash] = useState('10000');
  const [btFeeBps, setBtFeeBps] = useState('10');
  const [btSlipBps, setBtSlipBps] = useState('5');
  const [btCurrent, setBtCurrent] = useState<BacktestResult | null>(null);
  const [btHistory, setBtHistory] = useState<BacktestResult[]>([]);
  const [btBusy, setBtBusy] = useState(false);

  // Sessions & Audit Logs state
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [auditItems, setAuditItems] = useState<AuditLogItem[]>([]);

  async function refresh(silent = false) {
    if (!silent) setLoading(true);
    setError('');
    try {
      const [dash, integrations, recent] = await Promise.all([getDashboard(), getStatus(), getEvents()]);
      setDashboard(dash); setStatus(integrations); setEvents(recent); setUpdatedAt(new Date().toISOString());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить данные.');
    } finally { if (!silent) setLoading(false); }
  }

  useEffect(() => {
    const onUnauthorized = () => {
      setAuthUser(null); setDashboard(null); setPaperPortfolio(null); setPaperOrders([]);
      setRiskSettings(null); setAuthChecked(true); setError('Сессия завершилась. Войди снова.');
    };
    window.addEventListener('botvex:unauthorized', onUnauthorized);
    return () => window.removeEventListener('botvex:unauthorized', onUnauthorized);
  }, []);

  useEffect(() => {
    if (authInitStarted.current) return;
    authInitStarted.current = true;
    if (activationMode) { setAuthChecked(true); return; }
    window.Telegram?.WebApp?.ready?.(); window.Telegram?.WebApp?.expand?.();
    void getMe().then(async result => {
      let resolved = result;
      if (!result.authenticated && window.Telegram?.WebApp?.initData) {
        try { await exchangeTelegramAccount(); resolved = await getMe(); } catch { /* Unlinked Telegram stays on the login screen. */ }
      }
      setAuthUser(resolved.authenticated ? resolved.user : null);
      setAuthChecked(true);
      if (resolved.authenticated && resolved.user && !resolved.user.must_change_password) void refresh();
    }).catch(() => { setAuthUser(null); setAuthChecked(true); });
  }, []);

  useEffect(() => {
    if (!authUser || authUser.must_change_password) return;
    const timer = window.setInterval(() => { void refresh(true); }, 30_000);
    return () => window.clearInterval(timer);
  }, [authUser]);

  async function loadAiSignals(customList?: string) {
    setAiLoading(true);
    try {
      const data = await getAiSignals(customList ?? aiCustomSymbols);
      setAiScan(data);
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : 'Не удалось рассчитать Quant/AI сигналы.');
    } finally { setAiLoading(false); }
  }

  async function loadBacktests() {
    try {
      const list = await getBacktests(15);
      setBtHistory(list);
      if (list.length > 0 && !btCurrent) setBtCurrent(list[0]);
    } catch { /* ignore initial load error */ }
  }

  useEffect(() => {
    if (!authUser || authUser.must_change_password) return;
    setActionMessage('');
    if (tab === 'portfolio' || tab === 'trades') {
      void Promise.all([getPaperPortfolio(), getPaperOrders()]).then(([portfolio, orders]) => {
        setPaperPortfolio(portfolio); setPaperOrders(orders);
      }).catch((err: unknown) => setActionMessage(err instanceof Error ? err.message : 'Не удалось загрузить PAPER-данные.'));
    }
    if (tab === 'ai') {
      void loadAiSignals();
    }
    if (tab === 'backtests') {
      void loadBacktests();
    }
    if (tab === 'events') {
      void getPaperOrders().then(setPaperOrders).catch(() => {});
      if ((authUser.roles ?? []).some(r => r === 'OWNER' || r === 'ADMIN')) {
        void getAuditLogs(40).then(setAuditItems).catch(() => {});
      }
    }
    if (tab === 'settings') {
      void getPaperRiskSettings().then(setRiskSettings).catch((err: unknown) => setActionMessage(err instanceof Error ? err.message : 'Не удалось загрузить риск-настройки.'));
      void getSessions().then(setSessions).catch(() => {});
    }
  }, [tab, authUser]);

  async function handleAuthenticated(user: IdentityUser) {
    setError(''); setAuthUser(user); setAuthChecked(true);
    if (!user.must_change_password) {
      try { const result = await getMe(); if (result.user) setAuthUser(result.user); } catch { /* Session will be rechecked on next API request. */ }
      void refresh();
    }
  }

  async function handleLogout() {
    try { await logout(); } catch { /* Expired sessions are cleared locally below. */ }
    setAuthUser(null); setTab('overview'); setDashboard(null); setPaperPortfolio(null); setPaperOrders([]); setRiskSettings(null); setError('');
  }

  async function handleLinkTelegram() {
    try { await linkTelegramAccount(); window.alert('Telegram успешно привязан к аккаунту.'); }
    catch (err) { window.alert(err instanceof Error ? err.message : 'Не удалось привязать Telegram.'); }
  }

  if (activationMode && activationToken) return <ActivationScreen token={activationToken} mode={activationKind} onDone={() => { window.history.replaceState({}, '', '/'); setAuthUser(null); setAuthChecked(true); }} />;
  if (!authChecked) return <div className="auth-loading">Загрузка защищённой сессии…</div>;
  if (!authUser) return <LoginScreen onAuthenticated={handleAuthenticated} notice={error} />;
  if (authUser.must_change_password) return <ChangePasswordScreen forced onDone={() => { setAuthUser(null); setAuthChecked(true); }} />;

  async function submitPaperOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setActionBusy(true); setActionMessage('');
    try {
      const orderPayload = { symbol: orderSymbol.trim().toUpperCase(), side: orderSide, quantity: Number(orderQuantity), reference_price: Number(orderPrice) };
      const fingerprint = JSON.stringify(orderPayload);
      if (!pendingOrder.current || pendingOrder.current.fingerprint !== fingerprint) {
        pendingOrder.current = { fingerprint, key: `ui-${crypto.randomUUID()}` };
      }
      const order = await createPaperOrder({ ...orderPayload, idempotency_key: pendingOrder.current.key });
      pendingOrder.current = null;
      setActionMessage(`Симуляция выполнена: ${order.side} ${order.quantity} ${order.symbol} по введённой цене ${order.reference_price}. Реальный брокер не вызывался.`);
      const [portfolio, orders] = await Promise.all([getPaperPortfolio(), getPaperOrders()]); setPaperPortfolio(portfolio); setPaperOrders(orders); void refresh(true);
    } catch (err) { setActionMessage(err instanceof Error ? err.message : 'Не удалось создать PAPER-ордер.'); }
    finally { setActionBusy(false); }
  }

  async function handleExecuteSignal(symbol?: string, mode: 'single' | 'auto_top' = 'single') {
    setActionBusy(true); setActionMessage('');
    try {
      const res = await executeAiSignal({ mode, symbol, max_orders: 3, idempotency_prefix: `sig-${crypto.randomUUID().slice(0, 12)}` });
      if (res.executed_count > 0) {
        const summary = res.orders.map(o => `${o.side} ${o.quantity} ${o.symbol} @ $${o.reference_price}`).join(', ');
        setActionMessage(`Исполнено PAPER-ордеров (${res.executed_count}): ${summary}.`);
      } else {
        const reason = res.skipped[0]?.reason ?? 'нет подходящих сигналов, прошедших Risk Gate';
        setActionMessage(`Ордера не созданы: ${reason}`);
      }
      setPaperPortfolio(res.portfolio);
      await loadAiSignals();
      void refresh(true);
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : 'Ошибка исполнения сигнала.');
    } finally { setActionBusy(false); }
  }

  async function handleRunBacktest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBtBusy(true); setActionMessage('');
    try {
      const result = await runBacktest({
        symbol: btSymbol.trim().toUpperCase(),
        strategy: btStrategy,
        bars: Number(btBars),
        initial_cash: Number(btCash),
        fee_bps: Number(btFeeBps),
        slippage_bps: Number(btSlipBps),
      });
      setBtCurrent(result);
      await loadBacktests();
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : 'Не удалось выполнить бэктест.');
    } finally { setBtBusy(false); }
  }

  async function saveRiskLimits(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!riskSettings) return; setActionBusy(true); setActionMessage('');
    try { const next = await savePaperRiskSettings(riskSettings); setRiskSettings(next); setActionMessage('Риск-лимиты сохранены на сервере.'); }
    catch (err) { setActionMessage(err instanceof Error ? err.message : 'Не удалось сохранить лимиты риска.'); }
    finally { setActionBusy(false); }
  }

  async function toggleKillSwitch() {
    if (!riskSettings) return; setActionBusy(true); setActionMessage('');
    try { const next = await savePaperRiskSettings({ ...riskSettings, kill_switch: !riskSettings.kill_switch }); setRiskSettings(next); setActionMessage(next.kill_switch ? 'Kill switch включён: новые PAPER-ордера заблокированы.' : 'Kill switch выключен. Ограничения риска продолжают действовать.'); }
    catch (err) { setActionMessage(err instanceof Error ? err.message : 'Не удалось сохранить настройки.'); }
    finally { setActionBusy(false); }
  }

  async function handleRevokeSession(sessionId: string) {
    setActionBusy(true);
    try {
      await revokeSession(sessionId);
      const updated = await getSessions();
      setSessions(updated);
      setActionMessage('Сессия отозвана.');
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : 'Не удалось отозвать сессию.');
    } finally { setActionBusy(false); }
  }

  const userRoles = authUser.roles ?? [];
  const canManageUsers = userRoles.some(role => role === 'OWNER' || role === 'ADMIN');
  const canCreatePaperOrders = authUser.trading_access === 'paper' && userRoles.some(role => ['OWNER', 'ADMIN', 'TRADER'].includes(role));
  const canConfigureRisk = userRoles.some(role => role === 'OWNER' || role === 'ADMIN');
  const canRunBacktests = userRoles.some(role => ['OWNER', 'ADMIN', 'TRADER'].includes(role));
  const visibleTabs = tabs.filter(item => item.id !== 'users' || canManageUsers);
  const activeTab = visibleTabs.find((item) => item.id === tab) ?? visibleTabs[0];

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Zap size={21} fill="currentColor" /></div><div><b>BOTVEX</b><span>AI TRADER</span></div></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav>{visibleTabs.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}><Icon size={18} /><span>{label}</span>{id === 'events' && events.some((event) => event.level === 'warning' || event.level === 'error') && <i className="nav-dot" />}</button>)}</nav>
      <div className="sidebar-bottom"><div className="security-chip"><ShieldCheck size={17} /><div><b>Защита включена</b><span>LIVE заблокирован</span></div></div><div className="version">BOTVEX AI Trader <span>v0.4.0 · PRO PAPER</span></div></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div className="crumb"><span>BOTVEX</span><b>/</b><strong>{activeTab.label}</strong></div><div className="top-actions"><span className="mode-pill"><span /> PAPER MODE</span><button className="icon-button" aria-label="Обновить данные" onClick={() => void refresh()} disabled={loading}><RefreshCw size={17} className={loading ? 'spin' : ''} /></button><span className="identity-label">{authUser.login}</span>{window.Telegram?.WebApp?.initData && <button className="text-button link-telegram" onClick={() => void handleLinkTelegram()}>Привязать TG</button>}<button className="icon-button" aria-label="Выйти" title="Выйти" onClick={() => void handleLogout()}><LogOut size={16}/></button></div></header>
      <div className="page-content">
        <div className="page-heading"><div><div className="eyebrow">TRADING CONTROL CENTER</div><h1>{tab === 'overview' ? 'Обзор системы' : activeTab.label}</h1><p>{placeholderCopy(tab)}</p></div><div className="updated"><Clock3 size={14} /><span>{updatedAt ? `Обновлено ${formatDate(updatedAt)}` : 'Ожидание данных'}</span></div></div>
        {error && <div className="alert alert-error"><AlertTriangle size={18} /><div><b>Не удалось загрузить данные</b><span>{error}</span></div><button onClick={() => void refresh()}>Повторить</button></div>}
        {tab === 'overview' && <>
          <div className="notice"><div className="notice-icon"><ShieldCheck size={20} /></div><div className="notice-copy"><b>Безопасный режим активен</b><span>Реальные заявки не отправляются. Работают мультифакторный Quant-сканер, ATR риск-менеджер и событийный бэктестер в контуре PAPER.</span></div><span className="notice-tag">PAPER SIMULATION</span></div>
          <div className="metrics-grid">
            <Metric title="Баланс счёта" value={dashboard?.balance == null ? '—' : dashboard.balance.toLocaleString('ru-RU')} note="Виртуальный PAPER-счёт" icon={WalletCards} />
            <Metric title="Equity" value={dashboard?.equity == null ? '—' : dashboard.equity.toLocaleString('ru-RU')} note="По себестоимости позиций" icon={ChartNoAxesCombined} />
            <Metric title="Реализованный PnL" value={dashboard?.realized_pnl == null ? '—' : dashboard.realized_pnl.toLocaleString('ru-RU')} note="Результат симуляций" icon={ArrowUpRight} />
            <Metric title="Нереализованный PnL" value={dashboard?.unrealized_pnl == null ? '—' : dashboard.unrealized_pnl.toLocaleString('ru-RU')} note="Нет live-котировок" icon={ArrowDownRight} />
          </div>
          <div className="content-grid"><section className="panel integrations-panel"><div className="panel-heading"><div><h2>Состояние сервисов</h2><p>Последняя проверка доступности компонентов</p></div><span className="small-badge">{status.filter((s) => s.state === 'connected').length}/{status.length} online</span></div><div className="integration-list">{(status.length ? status : dashboard?.integrations ?? []).map((item) => <Integration key={item.name} item={item} />)}{loading && status.length === 0 && <div className="skeleton-list"><i /><i /><i /></div>}</div></section>
            <section className="panel events-panel"><div className="panel-heading"><div><h2>Последние события</h2><p>Системные уведомления и важные состояния</p></div><button className="text-button" onClick={() => setTab('events')}>Все события <span>→</span></button></div><div className="event-list">{events.map((event) => <EventRow key={event.id} event={event} />)}{events.length === 0 && <div className="empty-state"><CircleHelp size={22} /><span>{loading ? 'Загружаем события…' : 'Событий пока нет'}</span></div>}</div></section></div>
          <div className="bottom-grid"><div className="panel next-panel"><div className="section-icon blue"><BrainCircuit size={19} /></div><div><b>Quant & ИИ-сигналы</b><p>Ансамбль EMA/RSI/MACD/ATR/VWAP + автоматический расчёт SL/TP и проверка Risk Gate.</p></div><button className="text-button" onClick={() => setTab('ai')}>Открыть сканер →</button></div><div className="panel next-panel"><div className="section-icon green"><Database size={19} /></div><div><b>Бэктест-студия и PAPER-движок</b><p>Проверка стратегий на истории с комиссиями и проскальзыванием + транзакционный SQLite-леджер.</p></div><button className="text-button" onClick={() => setTab('backtests')}>Запустить тест →</button></div></div>
        </>}
        {tab === 'portfolio' && <section className="panel feature-panel"><div className="panel-heading"><div><h2>Виртуальный PAPER-счёт</h2><p>Симуляция; не подключена к брокеру или котировкам</p></div><span className="small-badge">SIMULATED</span></div>{paperPortfolio ? <><div className="paper-metrics"><Metric title="Виртуальные средства" value={money(paperPortfolio.cash)} note="После комиссий симуляции" icon={WalletCards}/><Metric title="Позиции по себестоимости" value={money(paperPortfolio.position_cost_basis)} note="Не рыночная оценка" icon={ChartNoAxesCombined}/><Metric title="Equity по себестоимости" value={money(paperPortfolio.equity_at_cost_basis)} note="Без live-котировок" icon={Activity}/></div><p className="feature-note">{paperPortfolio.message}</p><div className="table-wrap"><table><thead><tr><th>Символ</th><th>Количество</th><th>Средняя цена симуляции</th></tr></thead><tbody>{paperPortfolio.positions.map(pos => <tr key={pos.symbol}><td>{pos.symbol}</td><td>{pos.quantity}</td><td>{money(pos.average_price)}</td></tr>)}{paperPortfolio.positions.length === 0 && <tr><td colSpan={3} className="table-empty">Открытых виртуальных позиций нет.</td></tr>}</tbody></table></div></> : <div className="feature-loading">{loading ? 'Загрузка виртуального счёта…' : 'Данные пока не загружены.'}</div>}</section>}
        {tab === 'trades' && <div className="feature-stack">{canCreatePaperOrders && <section className="panel feature-panel"><div className="panel-heading"><div><h2>Создать PAPER-ордер</h2><p>Исполнение по указанной тобой цене — это не рыночная котировка</p></div><span className="small-badge">LIVE OFF</span></div><form className="paper-form" onSubmit={submitPaperOrder}><label>Тикер<input value={orderSymbol} onChange={e => setOrderSymbol(e.target.value)} required minLength={1} maxLength={20} pattern="[A-Za-z0-9._-]+" /></label><label>Сторона<select value={orderSide} onChange={e => setOrderSide(e.target.value as 'BUY' | 'SELL')}><option value="BUY">Покупка</option><option value="SELL">Продажа</option></select></label><label>Количество<input type="number" value={orderQuantity} onChange={e => setOrderQuantity(e.target.value)} min="0.000001" step="any" required /></label><label>Цена симуляции<input type="number" value={orderPrice} onChange={e => setOrderPrice(e.target.value)} min="0.000001" step="any" required /></label><button className="primary-button" type="submit" disabled={actionBusy}>{actionBusy ? 'Обработка…' : 'Выполнить симуляцию'}</button></form><p className="feature-note">Ордер проверяется серверными лимитами риска. Комиссия задаётся конфигурацией. Брокер не вызывается, котировки не загружаются.</p>{actionMessage && <div className="action-message" role="status">{actionMessage}</div>}</section>}<section className="panel feature-panel"><div className="panel-heading"><div><h2>История симуляций</h2><p>Сохранённые виртуальные ордера</p></div><span className="small-badge">{paperOrders.length} записей</span></div><div className="table-wrap"><table><thead><tr><th>Время</th><th>Сторона</th><th>Символ</th><th>Кол-во</th><th>Цена</th><th>Комиссия</th><th>PnL</th></tr></thead><tbody>{paperOrders.map(order => <tr key={order.id}><td>{formatDate(order.created_at)}</td><td><span className={order.side === 'BUY' ? 'side-buy' : 'side-sell'}>{order.side === 'BUY' ? 'Покупка' : 'Продажа'}</span></td><td>{order.symbol}</td><td>{order.quantity}</td><td>{money(order.reference_price)}</td><td>{money(order.fee)}</td><td>{order.realized_pnl ? money(order.realized_pnl) : '—'}</td></tr>)}{paperOrders.length === 0 && <tr><td colSpan={7} className="table-empty">История пока пуста.</td></tr>}</tbody></table></div></section></div>}
        {tab === 'ai' && (
          <div className="feature-stack">
            <section className="panel feature-panel">
              <div className="panel-heading">
                <div><h2><Sparkles size={16} /> Мультифакторный Quant & AI Сканер</h2><p>Ансамбль EMA(9/21/50), Wilder RSI(14), MACD, ATR(14), VWAP и Z-Score с предторговой проверкой Risk Gate</p></div>
                <span className="small-badge">{aiScan?.engine ?? 'QUANT ENSEMBLE'}</span>
              </div>
              <div className="quant-toolbar">
                <input value={aiCustomSymbols} onChange={e => setAiCustomSymbols(e.target.value)} placeholder="NVDA,AAPL,MSFT,SPY,BTC-USD,ETH-USD" aria-label="Список тикеров" />
                <button className="secondary-button" onClick={() => void loadAiSignals(aiCustomSymbols)} disabled={aiLoading}>{aiLoading ? 'Расчёт…' : 'Пересчитать сигналы'}</button>
                {canCreatePaperOrders && (
                  <button className="primary-button" onClick={() => void handleExecuteSignal(undefined, 'auto_top')} disabled={actionBusy || aiLoading}>
                    <Play size={14} /> Авто-исполнение топ сигналов (PAPER)
                  </button>
                )}
              </div>
              {actionMessage && <div className="action-message" role="status">{actionMessage}</div>}
              <div className="signals-grid">
                {(aiScan?.signals ?? []).map(sig => (
                  <div key={sig.symbol} className="signal-card">
                    <div className="signal-header">
                      <div>
                        <strong className="signal-symbol">{sig.symbol}</strong>
                        <span className="regime-pill">{regimeLabel(sig.regime)}</span>
                      </div>
                      <span className={`action-pill ${sig.action.toLowerCase()}`}>{sig.action} · {sig.confidence}%</span>
                    </div>
                    <p className="signal-thesis">{sig.thesis}</p>
                    <div className="signal-levels">
                      <div><span>Вход</span><b>{money(sig.entry_price)}</b></div>
                      <div><span>Stop-Loss (2x ATR)</span><b className="side-sell">{money(sig.stop_loss)}</b></div>
                      <div><span>Take-Profit (4.2x ATR)</span><b className="side-buy">{money(sig.take_profit)}</b></div>
                      <div><span>R:R / Размер</span><b>{sig.risk_reward}x · {sig.recommended_qty} шт.</b></div>
                    </div>
                    <div className="factor-tags">
                      {sig.factors.map(f => (
                        <span key={f.name} className={`factor-tag ${f.impact >= 0 ? 'pos' : 'neg'}`} title={f.detail}>
                          {f.name}: {f.impact > 0 ? `+${f.impact}` : f.impact}
                        </span>
                      ))}
                    </div>
                    <div className="signal-footer">
                      <span className={`risk-gate-badge ${sig.risk_gate_passed ? 'ok' : 'blocked'}`}>
                        {sig.risk_gate_passed ? '✓ Risk Gate пройден' : `✕ ${sig.risk_gate_reason}`}
                      </span>
                      {canCreatePaperOrders && sig.action !== 'HOLD' && (
                        <button
                          className="primary-button compact-btn"
                          disabled={actionBusy || !sig.risk_gate_passed}
                          onClick={() => void handleExecuteSignal(sig.symbol, 'single')}
                        >
                          Исполнить в PAPER
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        )}
        {tab === 'backtests' && (
          <div className="feature-stack">
            {canRunBacktests && (
              <section className="panel feature-panel">
                <div className="panel-heading"><div><h2>Запустить исторический бэктест</h2><p>Событийная симуляция по OHLCV барам с комиссиями, проскальзыванием и внутрибарными стопами ATR</p></div><span className="small-badge">NO LOOKAHEAD</span></div>
                <form className="paper-form backtest-form" onSubmit={handleRunBacktest}>
                  <label>Тикер<input value={btSymbol} onChange={e => setBtSymbol(e.target.value)} required pattern="[A-Za-z0-9._-]+" /></label>
                  <label>Стратегия<select value={btStrategy} onChange={e => setBtStrategy(e.target.value as typeof btStrategy)}>
                    <option value="ensemble_quant">Multi-Factor Quant Ensemble (EMA+RSI+MACD+VWAP)</option>
                    <option value="ema_trend_atr">EMA 9/21 Trend Crossover + ATR Trailing Stop</option>
                    <option value="vwap_zscore_reversion">VWAP / Bollinger Z-Score Mean Reversion</option>
                  </select></label>
                  <label>Баров истории (4H)<input type="number" min="80" max="800" value={btBars} onChange={e => setBtBars(e.target.value)} required /></label>
                  <label>Начальный капитал (USD)<input type="number" min="100" step="100" value={btCash} onChange={e => setBtCash(e.target.value)} required /></label>
                  <label>Комиссия (bps)<input type="number" min="0" max="200" step="1" value={btFeeBps} onChange={e => setBtFeeBps(e.target.value)} required /></label>
                  <label>Проскальзывание (bps)<input type="number" min="0" max="200" step="1" value={btSlipBps} onChange={e => setBtSlipBps(e.target.value)} required /></label>
                  <button className="primary-button" type="submit" disabled={btBusy}>{btBusy ? 'Моделирование…' : 'Запустить бэктест'}</button>
                </form>
                {actionMessage && <div className="action-message" role="status">{actionMessage}</div>}
              </section>
            )}
            {btCurrent && (
              <section className="panel feature-panel">
                <div className="panel-heading">
                  <div><h2>Результат: {btCurrent.symbol} · {btCurrent.strategy}</h2><p>{btCurrent.bars} баров · Капитал {money(btCurrent.initial_cash)} → {money(btCurrent.final_equity)}</p></div>
                  <span className="small-badge">{btCurrent.total_trades} сделок</span>
                </div>
                <div className="paper-metrics">
                  <Metric title="Доходность / Alpha" value={`${btCurrent.total_return_pct > 0 ? '+' : ''}${btCurrent.total_return_pct}%`} note={`Alpha к Buy&Hold: ${btCurrent.alpha_pct > 0 ? '+' : ''}${btCurrent.alpha_pct}%`} icon={ArrowUpRight} />
                  <Metric title="Sharpe / Sortino" value={`${btCurrent.sharpe_ratio} / ${btCurrent.sortino_ratio}`} note={`Win Rate: ${btCurrent.win_rate_pct}%`} icon={ChartNoAxesCombined} />
                  <Metric title="Profit Factor / Max DD" value={`${btCurrent.profit_factor}x`} note={`Макс. просадка: -${btCurrent.max_drawdown_pct}% · Ожидание: ${money(btCurrent.expectancy_usd)}`} icon={Activity} />
                </div>
                <EquityChart curve={btCurrent.equity_curve} />
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Вход</th><th>Выход</th><th>Кол-во</th><th>Цена входа</th><th>Цена выхода</th><th>PnL</th><th>Доходность</th><th>Причина</th></tr></thead>
                    <tbody>
                      {btCurrent.trades.map((t, i) => (
                        <tr key={`${t.entry_time}-${i}`}>
                          <td>{formatDate(t.entry_time)}</td>
                          <td>{formatDate(t.exit_time)}</td>
                          <td>{t.quantity}</td>
                          <td>{money(t.entry_price)}</td>
                          <td>{money(t.exit_price)}</td>
                          <td className={t.pnl >= 0 ? 'side-buy' : 'side-sell'}>{money(t.pnl)}</td>
                          <td className={t.return_pct >= 0 ? 'side-buy' : 'side-sell'}>{t.return_pct > 0 ? `+${t.return_pct}%` : `${t.return_pct}%`}</td>
                          <td><span className="small-badge">{t.reason}</span></td>
                        </tr>
                      ))}
                      {btCurrent.trades.length === 0 && <tr><td colSpan={8} className="table-empty">В выбранном окне сделок не совершено.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
            {btHistory.length > 1 && (
              <section className="panel feature-panel">
                <div className="panel-heading"><div><h2>Сохранённые прогоны</h2><p>Нажми на строку для просмотра кривой капитала и сделок</p></div><span className="small-badge">{btHistory.length} прогонов</span></div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Время</th><th>Символ</th><th>Стратегия</th><th>Доходность</th><th>Sharpe</th><th>Profit Factor</th><th>Max DD</th><th>Сделок</th></tr></thead>
                    <tbody>
                      {btHistory.map(run => (
                        <tr key={run.id} onClick={() => setBtCurrent(run)} style={{ cursor: 'pointer' }}>
                          <td>{formatDate(run.created_at)}</td>
                          <td><b>{run.symbol}</b></td>
                          <td>{run.strategy}</td>
                          <td className={run.total_return_pct >= 0 ? 'side-buy' : 'side-sell'}>{run.total_return_pct > 0 ? `+${run.total_return_pct}%` : `${run.total_return_pct}%`}</td>
                          <td>{run.sharpe_ratio}</td>
                          <td>{run.profit_factor}x</td>
                          <td>-{run.max_drawdown_pct}%</td>
                          <td>{run.total_trades}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        )}
        {tab === 'events' && (
          <div className="feature-stack">
            <section className="panel feature-panel">
              <div className="panel-heading"><div><h2>Системные события и исполнения PAPER</h2><p>Хронология состояния инфраструктуры и виртуальных сделок</p></div><span className="small-badge">LIVE FEED</span></div>
              <div className="event-list">
                {events.map((event) => <EventRow key={event.id} event={event} />)}
                {paperOrders.slice(0, 15).map(ord => (
                  <EventRow
                    key={`ord-${ord.id}`}
                    event={{
                      id: ord.id,
                      level: 'info',
                      title: `PAPER ${ord.side}: ${ord.quantity} ${ord.symbol} @ ${money(ord.reference_price)}`,
                      detail: `Статус: ${ord.status} · Комиссия: ${money(ord.fee)}${ord.realized_pnl ? ` · Реализованный PnL: ${money(ord.realized_pnl)}` : ''}`,
                      created_at: ord.created_at,
                    }}
                  />
                ))}
              </div>
            </section>
            {canManageUsers && auditItems.length > 0 && (
              <section className="panel feature-panel">
                <div className="panel-heading"><div><h2>Журнал аудита безопасности</h2><p>Регистрация входов, выпуска ссылок и изменения ролей</p></div><span className="small-badge">{auditItems.length} записей</span></div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Время</th><th>Действие</th><th>Статус</th><th>Актор</th><th>Цель</th></tr></thead>
                    <tbody>
                      {auditItems.map(item => (
                        <tr key={item.id}>
                          <td>{formatDate(item.created_at)}</td>
                          <td><b>{item.action}</b></td>
                          <td><span className={`user-status ${item.outcome === 'success' ? 'active' : 'disabled'}`}>{item.outcome}</span></td>
                          <td>{item.actor_user_id ? item.actor_user_id.slice(0, 8) : 'system'}</td>
                          <td>{item.target_user_id ? item.target_user_id.slice(0, 8) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        )}
        {tab === 'users' && canManageUsers && <UserManagement isOwner={userRoles.includes('OWNER')} />}
        {tab === 'settings' && (
          <div className="feature-stack">
            <section className="panel feature-panel"><div className="panel-heading"><div><h2>Риск-контроль PAPER</h2><p>Серверные лимиты; реальная торговля всегда заблокирована</p></div><span className="small-badge">LIVE OFF</span></div>{riskSettings ? <div className="risk-settings">{canConfigureRisk ? <><form className="risk-form" onSubmit={saveRiskLimits}><label>Максимальный размер ордера (USD)<input type="number" min="0.01" step="0.01" required value={riskSettings.max_order_notional} onChange={e => setRiskSettings(prev => prev ? { ...prev, max_order_notional: Number(e.target.value) } : prev)} /></label><label>Максимальный размер позиции (USD)<input type="number" min="0.01" step="0.01" required value={riskSettings.max_position_notional} onChange={e => setRiskSettings(prev => prev ? { ...prev, max_position_notional: Number(e.target.value) } : prev)} /></label><label>Дневной лимит реализованного убытка (USD)<input type="number" min="0.01" step="0.01" required value={riskSettings.daily_loss_limit} onChange={e => setRiskSettings(prev => prev ? { ...prev, daily_loss_limit: Number(e.target.value) } : prev)} /></label><button className="primary-button" type="submit" disabled={actionBusy}>{actionBusy ? "Сохранение…" : "Сохранить лимиты"}</button></form><div className="kill-row"><div><b>Аварийная блокировка</b><span>{riskSettings.kill_switch ? 'Включена — новые ордера заблокированы' : 'Выключена — лимиты риска всё равно применяются'}</span></div><button className={riskSettings.kill_switch ? 'primary-button danger-button' : 'primary-button'} onClick={() => void toggleKillSwitch()} disabled={actionBusy}>{riskSettings.kill_switch ? 'Отключить kill switch' : 'Включить kill switch'}</button></div></> : <p className="feature-note">Риск-настройки доступны только для чтения. Изменять лимиты может OWNER или ADMIN.</p>}</div> : <div className="feature-loading">Загрузка настроек риска…</div>}{actionMessage && <div className="action-message" role="status">{actionMessage}</div>}<p className="feature-note">Лимиты по умолчанию — технические защитные ограничения, не финансовая рекомендация. Значения можно изменить через защищённый API.</p></section>
            <section className="panel feature-panel">
              <div className="panel-heading"><div><h2>Сессии аккаунта</h2><p>Управление активными входами текущего оператора</p></div><span className="small-badge">{sessions.filter(s => s.active).length} активных</span></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Создана</th><th>Последняя активность</th><th>IP</th><th>Устройство</th><th>Статус</th><th>Действие</th></tr></thead>
                  <tbody>
                    {sessions.map(s => (
                      <tr key={s.id}>
                        <td>{formatDate(new Date(s.created_at * 1000).toISOString())}</td>
                        <td>{formatDate(new Date(s.last_seen_at * 1000).toISOString())}</td>
                        <td>{s.ip_address || '—'}</td>
                        <td>{(s.user_agent || 'Browser').slice(0, 48)}</td>
                        <td><span className={`user-status ${s.active ? 'active' : 'disabled'}`}>{s.active ? 'ACTIVE' : 'REVOKED'}</span></td>
                        <td>{s.active && <button className="text-button" disabled={actionBusy} onClick={() => void handleRevokeSession(s.id)}>Завершить</button>}</td>
                      </tr>
                    ))}
                    {sessions.length === 0 && <tr><td colSpan={6} className="table-empty">Данные о сессиях доступны при входе по логину и паролю.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        )}
        <footer><span>BOTVEX AI Trader <b>·</b> DEMO / PAPER only</span><span><ShieldCheck size={13} /> LIVE disabled by design</span></footer>
      </div>
    </main>
    <nav className="mobile-nav" aria-label="Основная навигация">{visibleTabs.filter((item) => ['overview', 'portfolio', 'trades', 'ai', 'backtests', 'settings', 'users'].includes(item.id)).map(({ id, label, icon: Icon }) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}><Icon size={19} /><span>{label === 'ИИ и стратегия' ? 'ИИ' : label === 'Настройки' ? 'Риск' : label === 'Пользователи' ? 'Доступ' : label}</span></button>)}</nav>
  </div>;
}

function money(value: number) { return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value); }

function EquityChart({ curve }: { curve: BacktestResult['equity_curve'] }) {
  if (!curve || curve.length < 2) return null;
  const w = 760;
  const h = 210;
  const pad = 24;
  const allVals = curve.flatMap(p => [p.equity, p.benchmark]);
  const minV = Math.min(...allVals);
  const maxV = Math.max(...allVals, minV + 1);
  const toX = (i: number) => pad + (i / (curve.length - 1)) * (w - pad * 2);
  const toY = (v: number) => h - pad - ((v - minV) / (maxV - minV)) * (h - pad * 2);
  const eqPoints = curve.map((p, i) => `${toX(i).toFixed(1)},${toY(p.equity).toFixed(1)}`).join(' ');
  const bmPoints = curve.map((p, i) => `${toX(i).toFixed(1)},${toY(p.benchmark).toFixed(1)}`).join(' ');
  return (
    <div className="equity-chart-wrap">
      <div className="chart-legend">
        <span><i className="dot-eq" /> Стратегия ({money(curve[curve.length - 1].equity)})</span>
        <span><i className="dot-bm" /> Buy & Hold ({money(curve[curve.length - 1].benchmark)})</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="equity-svg" role="img" aria-label="Кривая капитала стратегии против Buy & Hold">
        <polyline fill="none" stroke="#5d7298" strokeWidth="1.6" strokeDasharray="4 4" points={bmPoints} />
        <polyline fill="none" stroke="#46c995" strokeWidth="2.4" points={eqPoints} />
      </svg>
    </div>
  );
}

function Metric({ title, value, note, icon: Icon }: { title: string; value: string; note: string; icon: typeof WalletCards }) {
  return <div className="metric-card"><div className="metric-top"><span>{title}</span><div className="metric-icon"><Icon size={17} /></div></div><div className="metric-value">{value}</div><div className="metric-note"><span className="muted-dot" />{note}</div></div>;
}
function Integration({ item }: { item: IntegrationStatus }) {
  return <div className="integration-row"><div className={`integration-icon ${item.state}`}><Activity size={17} /></div><div className="integration-info"><b>{item.name}</b><span>{item.detail}</span></div><div className={`status-label ${item.state}`}><i />{statusLabel(item.state)}</div></div>;
}
function EventRow({ event }: { event: SystemEvent }) {
  const Icon = event.level === 'error' ? AlertTriangle : event.level === 'warning' ? AlertTriangle : Activity;
  return <div className="event-row"><div className={`event-icon ${event.level}`}><Icon size={15} /></div><div className="event-info"><b>{event.title}</b><span>{event.detail}</span><time>{formatDate(event.created_at)}</time></div></div>;
}
function placeholderCopy(tab: Tab) {
  const copy: Record<Tab, string> = {
    overview: 'Состояние торговой инфраструктуры и быстрый переход к модулям.',
    portfolio: 'Виртуальные средства и позиции по себестоимости симуляции.',
    trades: 'Ручное создание и история виртуальных ордеров без подключения к брокеру.',
    ai: 'Мультифакторный Quant & ИИ-сканер с расчётом уровней ATR Stop-Loss / Take-Profit и предторговой проверкой Risk Gate.',
    backtests: 'Событийный исторический бэктестер с учётом комиссий, проскальзывания и просадки.',
    events: 'Хронология системных событий, исполненных PAPER-ордеров и журнала аудита безопасности.',
    settings: 'Серверные лимиты риска, аварийный Kill Switch и управление активными сессиями.',
    users: 'Управление пользователями, ролями, сессиями и одноразовыми ссылками активации.',
  };
  return copy[tab];
}

export default App;
