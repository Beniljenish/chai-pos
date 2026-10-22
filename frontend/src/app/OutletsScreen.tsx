/**
 * Several outlets, one overview (README, "9.19"). An owner who runs more than one shop links the
 * owner logins (proving both passwords) and sees each outlet's day side by side. It never lets one
 * login act inside another shop: to work in another outlet you still log in there.
 */
import { Hint } from './Hint';
import { useCallback, useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { t } from '../lib/i18n';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading } from './Status';

interface Outlet {
  user_id: string;
  shop_id: string;
  name: string;
  is_me: boolean;
  sales_paise: number;
  bills: number;
  needs_you: number;
  open_online_orders: number;
}

export function OutletsScreen() {
  const [outlets, setOutlets] = useState<Outlet[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setOutlets((await api.get<{ outlets: Outlet[] }>('/links')).outlets);
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function link() {
    setBusy(true);
    setError(null);
    try {
      setOutlets((await api.post<{ outlets: Outlet[] }>('/links', { phone, password })).outlets);
      setAdding(false);
      setPhone('');
      setPassword('');
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  async function unlink(o: Outlet) {
    if (!window.confirm(t('Stop showing {name} here?', { name: o.name }))) return;
    setBusy(true);
    try {
      setOutlets((await api.delete<{ outlets: Outlet[] }>(`/links/${o.user_id}`)).outlets);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const totalSales = (outlets ?? []).reduce((n, o) => n + o.sales_paise, 0);
  return (
    <section className="outlets">
      <header className="manage-head">
        <h1>{t('My outlets')}</h1>
        <button onClick={() => setAdding(!adding)}>{adding ? t('Cancel') : t('+ Link an outlet')}</button>
      </header>
      <Hint>
        {t('See your outlets together. To change something inside another outlet, log in there with its own number: linking only lets you look.')}
      </Hint>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {adding && (
        <form
          className="panel-inline"
          onSubmit={(e) => {
            e.preventDefault();
            void link();
          }}
        >
          <p className="muted">{t('Enter the owner login of the other outlet. Its password is checked now and not kept.')}</p>
          <label>
            {t('Its owner’s mobile number')}
            <input value={phone} inputMode="tel" onChange={(e) => setPhone(e.target.value)} />
          </label>
          <label>
            {t('Its owner’s password')}
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
          </label>
          <button className="primary" disabled={busy || phone.trim() === '' || password === ''}>
            {t('Link this outlet')}
          </button>
        </form>
      )}
      {outlets === null ? (
        !error && <Loading />
      ) : (
        <>
          {outlets.length > 1 && (
            <p>
              {t('Sales today, all outlets')}: <strong className="num">{formatRupees(totalSales)}</strong>
            </p>
          )}
          <ul className="outlet-cards" aria-label={t('My outlets')}>
            {outlets.map((o) => (
              <li key={o.user_id} className="panel-inline">
                <h2>
                  {o.name}
                  {o.is_me && <span className="muted"> · {t('this one')}</span>}
                </h2>
                <dl>
                  <div>
                    <dt>{t('Sales today')}</dt>
                    <dd className="num">
                      {formatRupees(o.sales_paise)} · {t('{n} bills', { n: o.bills })}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('Needs you')}</dt>
                    <dd className="num">{o.needs_you}</dd>
                  </div>
                  <div>
                    <dt>{t('Open online orders')}</dt>
                    <dd className="num">{o.open_online_orders}</dd>
                  </div>
                </dl>
                {!o.is_me && (
                  <button className="quiet" disabled={busy} onClick={() => void unlink(o)}>
                    {t('Unlink')}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
