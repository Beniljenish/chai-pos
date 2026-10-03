/** This tablet's printer: how receipts reach paper. Saved on the tablet. */
import { useEffect, useRef, useState } from 'react';
import { db } from '../lib/db';
import { testRows } from '../lib/escpos';
import {
  bluetoothAvailable,
  bluetoothPrinterName,
  browserEnv,
  connectBluetooth,
  loadPrinter,
  printRows,
  savePrinter,
  type PrinterKind,
  type PrinterSettings,
} from '../lib/printer';

const KINDS: { kind: PrinterKind; label: string; hint: string }[] = [
  {
    kind: 'rawbt',
    label: 'RawBT app (Android + Bluetooth printer)',
    hint: 'Works with almost any Bluetooth thermal printer. Install the free RawBT app once, pair the printer in it, then choose this.',
  },
  {
    kind: 'bluetooth',
    label: 'Bluetooth LE, straight from the browser',
    hint: 'No app needed, but only some printers support it. Chrome on Android asks you to pick the printer once each time the app is opened.',
  },
  {
    kind: 'browser',
    label: "Browser's print dialog",
    hint: 'For a computer with a USB printer. On a phone it opens the system print screen every time.',
  },
];

export function PrinterSheet({ onClose }: { onClose(): void }) {
  const [s, setS] = useState<PrinterSettings | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadPrinter(db).then(setS);
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  async function change(patch: Partial<PrinterSettings>) {
    if (!s) return;
    const next = { ...s, ...patch };
    setS(next);
    setMessage(null);
    await savePrinter(db, next);
  }

  async function test() {
    if (!s) return;
    setMessage(null);
    try {
      if (s.kind === 'bluetooth' && !bluetoothPrinterName()) await connectBluetooth();
      await printRows(testRows(s.width), s, browserEnv);
      setMessage({ ok: true, text: 'Sent to the printer. Did the line of digits fit on one line?' });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : 'Could not print' });
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Printer"
        tabIndex={-1}
        ref={dialog}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sheet-head">
          <h2>Printer (this tablet)</h2>
          <button className="quiet" onClick={onClose}>
            Close
          </button>
        </header>
        {!s ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            <fieldset>
              <legend>How receipts reach the printer</legend>
              {KINDS.filter((k) => k.kind !== 'bluetooth' || bluetoothAvailable() || s.kind === 'bluetooth').map(
                (k) => (
                  <label key={k.kind} className="check email-switch">
                    <input
                      type="radio"
                      name="printer-kind"
                      checked={s.kind === k.kind}
                      onChange={() => void change({ kind: k.kind })}
                    />
                    <span>
                      {k.label}
                      <br />
                      <span className="muted">{k.hint}</span>
                    </span>
                  </label>
                ),
              )}
            </fieldset>
            {s.kind === 'rawbt' && (
              <p className="muted">
                Get RawBT from the Play Store:{' '}
                <a href="https://play.google.com/store/apps/details?id=ru.a402d.rawbtprinter" target="_blank" rel="noreferrer">
                  RawBT print service
                </a>
                . In RawBT, choose your printer under Settings → Connection.
              </p>
            )}
            {s.kind !== 'browser' && (
              <fieldset className="opt-row">
                <legend>Paper</legend>
                <label className="check">
                  <input type="radio" name="paper" checked={s.width === 32} onChange={() => void change({ width: 32 })} />
                  58 mm
                </label>
                <label className="check">
                  <input type="radio" name="paper" checked={s.width === 48} onChange={() => void change({ width: 48 })} />
                  80 mm
                </label>
              </fieldset>
            )}
            <label className="check">
              <input type="checkbox" checked={s.autoPrint} onChange={(e) => void change({ autoPrint: e.target.checked })} />
              Print every bill as soon as it is saved
            </label>
            {message && (
              <p className={message.ok ? 'ok' : 'error'} role={message.ok ? 'status' : 'alert'}>
                {message.text}
              </p>
            )}
            <div className="sheet-actions">
              <button className="primary" onClick={() => void test()}>
                Test print
              </button>
              <button onClick={onClose}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
