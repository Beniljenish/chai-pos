import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PosDB } from './db';
import { encode, testRows } from './escpos';
import { DEFAULT_PRINTER, loadPrinter, printRows, rawbtUrl, savePrinter, type PrintEnv } from './printer';

let db: PosDB;
beforeEach(() => {
  db = new PosDB(`printer-${Math.random()}`);
});

const env = (): PrintEnv & { [k: string]: ReturnType<typeof vi.fn> } => ({
  browserPrint: vi.fn(),
  openUrl: vi.fn(),
  bluetoothWrite: vi.fn().mockResolvedValue(undefined),
});

describe('printer setting', () => {
  it('defaults to the browser, 58 mm, auto-print; a saved choice is kept', async () => {
    expect(await loadPrinter(db)).toEqual(DEFAULT_PRINTER);
    await savePrinter(db, { kind: 'rawbt', width: 48, autoPrint: false, printKot: false });
    expect(await loadPrinter(db)).toEqual({ kind: 'rawbt', width: 48, autoPrint: false, printKot: false });
    // A tablet set up before table service keeps its choices and prints KOTs.
    await db.setMeta('printer', { kind: 'rawbt', width: 48, autoPrint: false });
    expect(await loadPrinter(db)).toEqual({ kind: 'rawbt', width: 48, autoPrint: false, printKot: true });
  });
});

describe('sending', () => {
  const rows = testRows(32);
  it('browser: the print dialog, no bytes', async () => {
    const e = env();
    await printRows(rows, { ...DEFAULT_PRINTER, kind: 'browser' }, e);
    expect(e.browserPrint).toHaveBeenCalledOnce();
    expect(e.openUrl).not.toHaveBeenCalled();
  });
  it('RawBT: the ESC/POS bytes as a rawbt: link', async () => {
    const e = env();
    await printRows(rows, { ...DEFAULT_PRINTER, kind: 'rawbt' }, e);
    const url = e.openUrl.mock.calls[0][0] as string;
    expect(url).toBe(rawbtUrl(encode(rows)));
    expect(url.startsWith('rawbt:base64,G0A')).toBe(true); // "G0A" = base64 of ESC @, the reset
  });
  it('Bluetooth: the same bytes, written to the printer', async () => {
    const e = env();
    await printRows(rows, { ...DEFAULT_PRINTER, kind: 'bluetooth' }, e);
    expect([...e.bluetoothWrite.mock.calls[0][0]]).toEqual([...encode(rows)]);
  });
});
