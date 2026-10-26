import { useState, type FormEvent, type ReactNode } from 'react';
import { ShieldCheck, Zap } from 'lucide-react';
import { activateAccount, changePassword, login, resetPassword } from './api';
import type { IdentityUser } from './api';

export function LoginScreen({ onAuthenticated, notice = '' }: { onAuthenticated: (user: IdentityUser) => void; notice?: string }) {
  const [loginName, setLoginName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await login(loginName, password);
      onAuthenticated({ login: result.login, roles: result.roles, permissions: [], must_change_password: result.must_change_password });
    } catch (err) { setError(err instanceof Error ? err.message : 'Не удалось войти.'); }
    finally { setBusy(false); }
  }
  return <AuthShell title="Вход в систему" subtitle="Защищённый доступ к BOTVEX AI Trader">{notice && <div className="auth-error" role="status">{notice}</div>}<form className="auth-form" onSubmit={submit}><label>Логин<input autoComplete="username" required value={loginName} onChange={e => setLoginName(e.target.value)} maxLength={80} /></label><label>Пароль<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} maxLength={256} /></label>{error && <div className="auth-error" role="alert">{error}</div>}<button className="primary-button" type="submit" disabled={busy}>{busy ? 'Проверка…' : 'Войти'}</button><p className="auth-footnote">Сессия хранится в HttpOnly cookie. Не используй общий или публичный компьютер для входа.</p></form></AuthShell>;
}

export function ChangePasswordScreen({ forced, onDone }: { forced: boolean; onDone: () => void }) {
  const [current, setCurrent] = useState(''); const [next, setNext] = useState(''); const [repeat, setRepeat] = useState('');
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('');
    if (next !== repeat) { setError('Пароли не совпадают.'); return; }
    if (next.length < 12) { setError('Новый пароль должен содержать минимум 12 символов.'); return; }
    setBusy(true);
    try { await changePassword(current, next); onDone(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Не удалось изменить пароль.'); }
    finally { setBusy(false); }
  }
  return <AuthShell title="Смена пароля" subtitle={forced ? 'Первый вход: установи постоянный пароль.' : 'Обнови пароль аккаунта.'}><form className="auth-form" onSubmit={submit}>{!forced && <label>Текущий пароль<input type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} required /></label>}<label>Новый пароль<input type="password" autoComplete="new-password" value={next} onChange={e => setNext(e.target.value)} minLength={12} maxLength={256} required /></label><label>Повтори новый пароль<input type="password" autoComplete="new-password" value={repeat} onChange={e => setRepeat(e.target.value)} minLength={12} maxLength={256} required /></label>{error && <div className="auth-error" role="alert">{error}</div>}<button className="primary-button" disabled={busy}>{busy ? 'Сохранение…' : 'Сменить пароль'}</button><p className="auth-footnote">После смены пароля текущие сессии отзываются; войди заново.</p></form></AuthShell>;
}

export function ActivationScreen({ token, onDone, mode = 'activate' }: { token: string; onDone: () => void; mode?: 'activate' | 'reset' }) {
  const [password, setPassword] = useState(''); const [repeat, setRepeat] = useState('');
  const [error, setError] = useState(''); const [done, setDone] = useState(false); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('');
    if (password !== repeat) { setError('Пароли не совпадают.'); return; }
    setBusy(true);
    try { if (mode === 'reset') await resetPassword(token, password); else await activateAccount(token, password); setDone(true); }
    catch (err) { setError(err instanceof Error ? err.message : 'Ссылка активации недействительна.'); }
    finally { setBusy(false); }
  }
  return <AuthShell title={done ? (mode === 'reset' ? 'Пароль обновлён' : 'Аккаунт активирован') : (mode === 'reset' ? 'Сброс пароля' : 'Активация аккаунта')} subtitle={done ? 'Теперь можно войти с новым паролем.' : 'Установи пароль. Ссылка одноразовая и ограничена по времени.'}>{done ? <button className="primary-button" onClick={onDone}>Перейти ко входу</button> : <form className="auth-form" onSubmit={submit}><label>Новый пароль<input type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} minLength={12} maxLength={256} required /></label><label>Повтори пароль<input type="password" autoComplete="new-password" value={repeat} onChange={e => setRepeat(e.target.value)} minLength={12} maxLength={256} required /></label>{error && <div className="auth-error" role="alert">{error}</div>}<button className="primary-button" disabled={busy}>{busy ? 'Сохранение…' : mode === 'reset' ? 'Сохранить новый пароль' : 'Активировать аккаунт'}</button></form>}</AuthShell>;
}

function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return <main className="auth-shell"><section className="auth-card"><div className="auth-brand"><div className="brand-mark"><Zap size={21} fill="currentColor" /></div><div><b>BOTVEX</b><span>AI TRADER</span></div></div><div className="auth-icon"><ShieldCheck size={22} /></div><h1>{title}</h1><p>{subtitle}</p>{children}<div className="auth-security"><ShieldCheck size={14} /> PAPER only · LIVE торговля отключена</div></section></main>;
}
