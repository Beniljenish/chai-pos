/**
 * The cash drawer on this tablet: start a shift, pay in / pay out, end it with a
 * blind count. Works offline; everything is sent later like bills.
 */
import { useState } from 'react';
import { db } from '../lib/db';
import { formatRupees } from '../lib/gst';
import {
  NOTES,
  drawerTotalPaise,
  endShift,
  recordCash,
  rupeesToPaise,
  shiftsOn,
  startShift,
  type LocalShift,
} from '../lib/shift';
import { HandoverCount, type HandoverState } from './HandoverCount';
import { Sheet } from './Sheet';
import { useSession } from './session';

const time = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', timeStyle: 'short' }).format(new Date(iso));

/** Asked at the first bill when no shift is open. */
export function StartShiftSheet({ onStarted, onClose }: { onStarted(s: LocalShift): void; onClose(): void }) {
  const { user, lastCounted, reloadShift } = useSession();
  const [amount, setAmount] = useState(lastCounted ? String(lastCounted.countedPaise / 100) : '');
  const [error, setError] = useState<string | null>(null);
  const paise = rupeesToPaise(amount);

  async function start() {
    if (!user) return;
    if (Number.isNaN(paise)) return setError('Enter the cash in the drawer, in rupees (0 if empty).');
    try {
      const s = await startShift(db, paise, { id: user.id, name: user.name });
      await reloadShift();
      onStarted(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the shift');
    }
  }

  return (
    <Sheet title="Start shift" onClose={onClose}>
      <p>Count the cash in the drawer before the first sale. At the end of the shift it is counted again.</p>
      {lastCounted && (
        <p className="muted">
          {lastCounted.byName} counted {formatRupees(lastCounted.countedPaise)} at the end of the last shift
          ({time(lastCounted.at)}). Change it if the drawer holds something else now.
        </p>
      )}
      <label>
        Cash in the drawer now (₹)
        <input
          inputMode="decimal"
          value={amount}
          autoFocus
          onChange={(e) => {
            setAmount(e.target.value.replace(/[^0-9.]/g, ''));
            setError(null);
          }}
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="sheet-actions">
        <button className="primary" onClick={() => void start()}>
          Start shift{Number.isNaN(paise) ? '' : ` with ${formatRupees(paise)}`}
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Sheet>
  );
}

const PAY_OUT_REASONS = ['Milk', 'Supplier', 'Owner took cash', 'Staff advance'];
const PAY_IN_REASONS = ['Change added', 'Owner added cash'];

function CashSheet({ kind, onClose }: { kind: 'pay_out' | 'pay_in'; onClose(): void }) {
  const { user, worker } = useSession();
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const paise = rupeesToPaise(amount);
  const out = kind === 'pay_out';

  async function save() {
    if (!user) return;
    if (Number.isNaN(paise) || paise <= 0) return setError('Enter the amount in rupees.');
    if (!reason.trim()) return setError(out ? 'Say what the money was for.' : 'Say where the money came from.');
    try {
      await recordCash(db, kind, paise, reason, { id: user.id, name: user.name });
      void worker?.kick();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save');
    }
  }

  return (
    <Sheet title={out ? 'Paid out of the drawer' : 'Put into the drawer'} onClose={onClose}>
      <label>
        Amount (₹)
        <input
          inputMode="decimal"
          value={amount}
          autoFocus
          onChange={(e) => {
            setAmount(e.target.value.replace(/[^0-9.]/g, ''));
            setError(null);
          }}
        />
      </label>
      <label>
        {out ? 'What for' : 'From where'}
        <input value={reason} maxLength={120} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="chips" role="group" aria-label="Common reasons">
        {(out ? PAY_OUT_REASONS : PAY_IN_REASONS).map((r) => (
          <button key={r} className="chip" aria-pressed={reason === r} onClick={() => setReason(r)}>
            {r}
          </button>
        ))}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="sheet-actions">
        <button className="primary" onClick={() => void save()}>
          Save{Number.isNaN(paise) || paise <= 0 ? '' : ` ${formatRupees(paise)}`}
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Sheet>
  );
}

/** Blind count: the person counting never sees what the drawer should hold. */
function EndShiftSheet({ shift, onClose }: { shift: LocalShift; onClose(): void }) {
  const { user, worker, reloadShift } = useSession();
  const [notes, setNotes] = useState<Partial<Record<number, string>>>({});
  const [coins, setCoins] = useState('');
  const [note, setNote] = useState('');
  const [done, setDone] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [handover, setHandover] = useState<HandoverState>('loading');
  const total = drawerTotalPaise(notes, coins);
  const someoneElse = user && shift.openedById !== user.id;
  const stockFirst = handover === 'loading' || handover === 'todo';

  async function end() {
    if (!user) return;
    try {
      await endShift(db, total, note, { id: user.id, name: user.name });
      await reloadShift();
      void worker?.kick();
      setDone(total);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not end the shift');
    }
  }

  if (done !== null)
    return (
      <Sheet title="Shift ended" onClose={onClose}>
        <p className="first-password" role="status">
          You counted <strong className="num">{formatRupees(done)}</strong>. The next shift starts from this amount.
          The owner sees whether it matches the sales.
        </p>
        <div className="sheet-actions">
          <button className="primary" onClick={onClose}>
            Done
          </button>
        </div>
      </Sheet>
    );

  return (
    <Sheet title="End shift: count the drawer" onClose={onClose}>
      {someoneElse && (
        <p className="warn">
          This is {shift.openedByName}&apos;s shift. Count the drawer now to take it over; the count is recorded under
          your name.
        </p>
      )}
      <HandoverCount shiftId={shift.id} onState={setHandover} />
      <p className="muted">Count every note and coin in the drawer, including the cash the shift started with.</p>
      <ul className="note-count">
        {NOTES.map((n) => (
          <li key={n}>
            <label htmlFor={`note-${n}`}>₹{n} notes</label>
            <input
              id={`note-${n}`}
              inputMode="numeric"
              value={notes[n] ?? ''}
              placeholder="0"
              onChange={(e) => setNotes((x) => ({ ...x, [n]: e.target.value.replace(/\D/g, '') }))}
            />
            <span className="num muted">{notes[n] ? formatRupees(Number(notes[n]) * n * 100) : ''}</span>
          </li>
        ))}
        <li>
          <label htmlFor="coins">Coins (₹ total)</label>
          <input
            id="coins"
            inputMode="decimal"
            value={coins}
            placeholder="0"
            onChange={(e) => setCoins(e.target.value.replace(/[^0-9.]/g, ''))}
          />
          <span />
        </li>
      </ul>
      <p className="count-total">
        Counted: <strong className="num">{formatRupees(total)}</strong>
      </p>
      <label>
        Note (optional)
        <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="sheet-actions">
        <button className="primary" disabled={stockFirst} onClick={() => void end()}>
          End shift with {formatRupees(total)}
        </button>
        <button onClick={onClose}>Not yet</button>
      </div>
    </Sheet>
  );
}

/** Today screen: the drawer's shift and its actions. */
export function ShiftPanel() {
  const { catalogue, shift } = useSession();
  const [open, setOpen] = useState<'start' | 'pay_out' | 'pay_in' | null>(null);
  // Held here, not read from the session: ending clears the session's shift, and
  // the sheet must stay up to confirm the count.
  const [ending, setEnding] = useState<LocalShift | null>(null);
  if (!shiftsOn(catalogue?.shop.cash_shifts)) return null;

  return (
    <section className="shift-panel" aria-label="Cash drawer">
      {shift ? (
        <>
          <p>
            <strong>Shift:</strong> {shift.openedByName} since {time(shift.openedAt)}, started with{' '}
            <span className="num">{formatRupees(shift.openingFloatPaise)}</span>
          </p>
          <div className="shift-actions">
            <button onClick={() => setOpen('pay_out')}>Paid out</button>
            <button onClick={() => setOpen('pay_in')}>Paid in</button>
            <button className="primary" onClick={() => setEnding(shift)}>
              End shift
            </button>
          </div>
        </>
      ) : (
        <div className="shift-actions">
          <p className="muted">No shift open. It starts with the first bill.</p>
          <button onClick={() => setOpen('start')}>Start shift now</button>
        </div>
      )}
      {open === 'start' && <StartShiftSheet onStarted={() => setOpen(null)} onClose={() => setOpen(null)} />}
      {(open === 'pay_out' || open === 'pay_in') && <CashSheet kind={open} onClose={() => setOpen(null)} />}
      {ending && <EndShiftSheet shift={ending} onClose={() => setEnding(null)} />}
    </section>
  );
}
