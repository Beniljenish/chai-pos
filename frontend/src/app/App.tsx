import { useState } from 'react';
import { BillingScreen } from './BillingScreen';
import { BillsScreen } from './BillsScreen';
import { DeviceSetupScreen } from './DeviceSetupScreen';
import { LoginScreen } from './LoginScreen';
import { AccountButton, SetPasswordScreen } from './PasswordForm';
import { ManageScreen } from './ManageScreen';
import { DayEndScreen } from './DayEndScreen';
import { useSession } from './session';
import { TablesScreen } from './TablesScreen';
import { hasTables } from '../lib/table';


function SyncBadge() {
  const { sync, worker } = useSession();
  if (!sync) return null;
  // Long text for tablets, short for phones (CSS picks one).
  let text: string;
  let short: string;
  let tone: 'ok' | 'wait' | 'bad';
  if (sync.rejected > 0) {
    text = `${sync.rejected} bill${sync.rejected > 1 ? 's' : ''} need the owner`;
    short = `${sync.rejected} problem${sync.rejected > 1 ? 's' : ''}`;
    tone = 'bad';
  } else if (sync.pending > 0) {
    text = sync.syncing ? `Sending ${sync.pending}…` : `${sync.pending} waiting to send`;
    short = `${sync.pending} waiting`;
    tone = 'wait';
  } else {
    text = 'All bills sent';
    short = 'Sent';
    tone = 'ok';
  }
  return (
    <button
      className={`sync-badge ${tone}`}
      onClick={() => void worker?.kick()}
      title={sync.lastError ?? 'Tap to send now'}
      aria-label={sync.lastError ? `${text}. ${sync.lastError}` : text}
      aria-live="polite"
    >
      <span className="dot" aria-hidden="true" />
      <span className="long" aria-hidden="true">{text}</span>
      <span className="short" aria-hidden="true">{short}</span>
    </button>
  );
}

export function App() {
  const { phase, user } = useSession();
  if (phase === 'loading') return <main className="centered" aria-busy="true" />;
  if (phase === 'login') return <LoginScreen />;
  if (phase === 'password') return <SetPasswordScreen />;
  if (phase === 'device') return <DeviceSetupScreen />;
  // Keyed by person: whoever logs in next starts on New bill, not on the
  // screen the previous person left open (often the owner's Manage).
  return <Shell key={user?.id} />;
}

function Shell() {
  const { user, device, catalogue, sync, notice, logout } = useSession();
  const [tab, setTab] = useState<'bill' | 'tables' | 'today' | 'stock'>('bill');

  const isOwner = user?.role === 'owner';
  const tables = hasTables(catalogue);

  return (
    <div className="app">
      <header className="topbar">
        <div className="where">
          <strong>{catalogue?.shop.name ?? 'Chai POS'}</strong>
          <span className="muted">
            {device?.name} ({device?.code}), <AccountButton />
          </span>
        </div>
        <nav className="tabs" aria-label="Screens">
          <button aria-pressed={tab === 'bill'} onClick={() => setTab('bill')} aria-label="New bill">
            <span className="long">New bill</span>
            <span className="short">Bill</span>
          </button>
          {tables && (
            <button aria-pressed={tab === 'tables'} onClick={() => setTab('tables')}>
              Tables
            </button>
          )}
          <button aria-pressed={tab === 'today'} onClick={() => setTab('today')}>
            Today
          </button>
          {/* Cashiers: batches, wastage and the blind count. They never see stock levels. */}
          <button aria-pressed={tab === 'stock'} onClick={() => setTab('stock')}>
            {isOwner ? 'Manage' : 'Stock'}
          </button>
        </nav>
        <SyncBadge />
        <button className="quiet" onClick={logout}>
          Log out
        </button>
      </header>
      {(notice || (sync?.needsLogin && sync.lastError)) && (
        <p className="banner" role="status">
          {notice ?? sync?.lastError}
        </p>
      )}
      {tab === 'bill' ? (
        <BillingScreen />
      ) : tab === 'tables' && tables ? (
        <TablesScreen />
      ) : tab === 'today' ? (
        <BillsScreen />
      ) : isOwner ? (
        <ManageScreen />
      ) : (
        <main className="manage">
          <DayEndScreen />
        </main>
      )}
    </div>
  );
}
