/**
 * A ticket on screen exactly as it prints (KOT, cancel ticket, bill at the table):
 * the same rows go to the printer, so what staff see is what the kitchen gets.
 */
import { useEffect, useState } from 'react';
import { db } from '../lib/db';
import type { Row } from '../lib/escpos';
import { browserEnv, loadPrinter, printRows } from '../lib/printer';
import { PrinterSheet } from './PrinterSettings';

export function TicketPreview({
  title,
  rows,
  autoPrint,
  onClose,
}: {
  title: string;
  rows: Row[];
  autoPrint: boolean;
  onClose(): void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  async function print() {
    setError(null);
    try {
      await printRows(rows, await loadPrinter(db), browserEnv);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not print');
    }
  }

  useEffect(() => {
    if (autoPrint) void print();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="receipt-wrap">
        <article className="receipt ticket">
          {rows.map((r, i) => (
            <div key={i} className={`${r.big ? 'big' : ''} ${r.bold ? 'bold' : ''} ${r.align === 'center' ? 'center' : ''}`}>
              {r.text || ' '}
            </div>
          ))}
        </article>
        {error && (
          <p className="error no-print" role="alert">
            {error}{' '}
            <button className="quiet" onClick={() => setSettingsOpen(true)}>
              Printer settings
            </button>
          </p>
        )}
        <div className="sheet-actions no-print">
          <button className="primary" onClick={onClose} autoFocus>
            Done
          </button>
          <button onClick={() => void print()}>Print again</button>
        </div>
      </div>
      {settingsOpen && <PrinterSheet onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
