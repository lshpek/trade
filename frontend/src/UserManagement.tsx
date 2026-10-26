import { useEffect, useState, type FormEvent } from 'react';
import { Copy, KeyRound, RefreshCw, ShieldAlert, UserPlus, Users } from 'lucide-react';
import {
  assignOwnerRole,
  createUser,
  disableUser,
  getUsers,
  issueActivationLink,
  issueResetPasswordLink,
  reactivateUser,
  revokeUserSessions,
  updateUser,
  type ManagedUser,
} from './api';

export default function UserManagement({ isOwner }: { isOwner: boolean }) {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [search, setSearch] = useState('');
  const [login, setLogin] = useState('trader01');
  const [role, setRole] = useState('VIEWER');
  const [access, setAccess] = useState('read');
  const [expiration, setExpiration] = useState('never');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [activationUrl, setActivationUrl] = useState('');
  const [linkTitle, setLinkTitle] = useState('Одноразовая ссылка активации');

  async function load() {
    try {
      const result = await getUsers(search);
      setUsers(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить пользователей.');
    }
  }
  useEffect(() => { void load(); }, [search]);

  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setMessage(''); setActivationUrl('');
    if (!window.confirm(`Создать пользователя ${login} с ролью ${role}, доступом ${access}, сроком ${expiration}?`)) return;
    setBusy(true);
    try {
      const result = await createUser({ login, role, trading_access: access, expiration });
      setMessage(result.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось создать пользователя.');
    } finally { setBusy(false); }
  }

  async function issue(id: string) {
    setBusy(true); setError(''); setMessage(''); setActivationUrl('');
    try {
      const result = await issueActivationLink(id);
      setLinkTitle('Одноразовая ссылка активации');
      setActivationUrl(result.activation_url);
      setMessage('Одноразовая ссылка активации создана. Скопируй и передай пользователю по защищённому каналу.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось создать ссылку.');
    } finally { setBusy(false); }
  }

  async function issueReset(user: ManagedUser) {
    if (!window.confirm(`Выпустить одноразовую ссылку сброса пароля для ${user.login}?`)) return;
    setBusy(true); setError(''); setMessage(''); setActivationUrl('');
    try {
      const result = await issueResetPasswordLink(user.id);
      setLinkTitle(`Одноразовая ссылка сброса пароля (${user.login})`);
      setActivationUrl(result.reset_url);
      setMessage(`Ссылка сброса пароля для ${user.login} выпущена. Передай её по защищённому каналу.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось выпустить ссылку сброса пароля.');
    } finally { setBusy(false); }
  }

  async function promoteOwner(user: ManagedUser) {
    const confirmed = window.prompt(`Для назначения роли OWNER пользователю ${user.login} введи его точный логин:`);
    if (!confirmed) return;
    setBusy(true); setError(''); setMessage('');
    try {
      await assignOwnerRole(user.id, confirmed);
      setMessage(`Пользователь ${user.login} повышен до OWNER; его активные сессии отозваны.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось назначить OWNER.');
    } finally { setBusy(false); }
  }

  async function revoke(user: ManagedUser) {
    if (!window.confirm(`Отозвать все активные сессии пользователя ${user.login}?`)) return;
    setBusy(true); setError(''); setMessage('');
    try {
      await revokeUserSessions(user.id);
      setMessage(`Активные сессии пользователя ${user.login} отозваны.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось отозвать сессии.');
    } finally { setBusy(false); }
  }

  async function toggle(user: ManagedUser) {
    setBusy(true); setError(''); setMessage('');
    try {
      const expiryPassed = Boolean(user.expires_at && new Date(user.expires_at).getTime() <= Date.now());
      if (user.status === 'EXPIRED' || (user.status === 'DISABLED' && expiryPassed)) await updateUser(user.id, { status: 'ACTIVE', expiration: '30_days' });
      else if (user.status === 'DISABLED') await reactivateUser(user.id);
      else await disableUser(user.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось изменить статус.');
    } finally { setBusy(false); }
  }

  return (
    <div className="user-admin-grid">
      <section className="panel feature-panel">
        <div className="panel-heading"><div><h2><UserPlus size={16} /> Создать пользователя</h2><p>Новый аккаунт без пароля до активации</p></div><span className="small-badge">INVITE ONLY</span></div>
        <form className="user-create-form" onSubmit={submit}>
          <label>Логин<input value={login} onChange={e => setLogin(e.target.value)} minLength={3} maxLength={32} pattern="[A-Za-z0-9_.-]+" required /></label>
          <label>Роль<select value={role} onChange={e => setRole(e.target.value)}><option value="VIEWER">VIEWER — просмотр</option><option value="TRADER">TRADER — PAPER</option>{isOwner && <option value="ADMIN">ADMIN — управление</option>}</select></label>
          <label>Торговый доступ<select value={access} onChange={e => setAccess(e.target.value)}><option value="read">read — только чтение</option><option value="paper">paper — PAPER операции</option><option value="disabled">disabled — без торговых данных</option>}</select></label>
          <label>Срок действия<select value={expiration} onChange={e => setExpiration(e.target.value)}><option value="never">Бессрочно</option><option value="7_days">7 дней</option><option value="30_days">30 дней</option><option value="90_days">90 дней</option></select></label>
          <div className="permission-preview">
            <b>Предпросмотр доступа</b>
            <span>{role === 'VIEWER' ? 'Чтение портфеля, истории и доступных стратегий.' : role === 'TRADER' ? 'Просмотр данных и PAPER-ордера при trading_access=paper.' : 'Административные действия в пределах делегированных разрешений.'}</span>
            <span>{access === 'read' ? 'Запись ордеров запрещена.' : access === 'paper' ? 'Доступ к PAPER зависит также от роли.' : 'Доступ к PAPER API будет заблокирован.'}</span>
            <span>LIVE торговля запрещена для всех ролей.</span>
          </div>
          <button className="primary-button" disabled={busy}>{busy ? 'Обработка…' : 'Создать аккаунт'}</button>
        </form>
        {message && <div className="action-message" role="status">{message}</div>}
        {error && <div className="auth-error admin-error" role="alert">{error}</div>}
        {activationUrl && (
          <div className="activation-output">
            <label>{linkTitle}<input readOnly value={activationUrl} /></label>
            <button className="secondary-button" onClick={() => void navigator.clipboard?.writeText(activationUrl)}><Copy size={14} /> Копировать ссылку</button>
          </div>
        )}
      </section>
      <section className="panel feature-panel">
        <div className="panel-heading"><div><h2><Users size={16} /> Пользователи</h2><p>Роли, состояние и срок доступа</p></div><button className="icon-button" aria-label="Обновить пользователей" onClick={() => void load()}><RefreshCw size={15}/></button></div>
        <div className="users-search"><input aria-label="Поиск по логину" placeholder="Поиск по логину…" value={search} onChange={e => setSearch(e.target.value)} /></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Логин</th><th>Роль</th><th>Статус</th><th>Доступ</th><th>Срок</th><th>Действия</th></tr></thead>
            <tbody>
              {users.map(user => (
                <tr key={user.id}>
                  <td>{user.login}</td>
                  <td>{user.role}</td>
                  <td><span className={`user-status ${user.status?.toLowerCase()}`}>{user.status}</span></td>
                  <td>{user.trading_access}</td>
                  <td>{user.expires_at ? new Date(user.expires_at).toLocaleDateString('ru-RU') : 'Бессрочно'}</td>
                  <td>
                    <div className="user-actions">
                      {user.status === 'PENDING_ACTIVATION' && (isOwner || user.role !== 'ADMIN') && <button className="text-button" disabled={busy} onClick={() => void issue(user.id)}>Ссылка</button>}
                      {user.status === 'ACTIVE' && (isOwner || (user.role !== 'ADMIN' && user.role !== 'OWNER')) && <button className="text-button" disabled={busy} onClick={() => void issueReset(user)} title="Выпустить одноразовую ссылку сброса пароля"><KeyRound size={12} /> Сброс</button>}
                      {user.role !== 'OWNER' && (isOwner || user.role !== 'ADMIN') && user.status !== 'PENDING_ACTIVATION' && <button className="text-button" disabled={busy} onClick={() => void toggle(user)}>{user.status === 'EXPIRED' || (user.status === 'DISABLED' && Boolean(user.expires_at && new Date(user.expires_at).getTime() <= Date.now())) ? 'Продлить +30д' : user.status === 'DISABLED' ? 'Включить' : 'Отключить'}</button>}
                      {user.status === 'ACTIVE' && (isOwner || (user.role !== 'ADMIN' && user.role !== 'OWNER')) && <button className="text-button" disabled={busy} onClick={() => void revoke(user)}>Сессии</button>}
                      {isOwner && user.status === 'ACTIVE' && user.role !== 'OWNER' && <button className="text-button" disabled={busy} onClick={() => void promoteOwner(user)} title="Назначить владельцем"><ShieldAlert size={12} /> OWNER</button>}
                    </div>
                  </td>
                </tr>
              ))}
              {users.length === 0 && <tr><td colSpan={6} className="table-empty">Пользователей нет или поиск ничего не нашёл.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
