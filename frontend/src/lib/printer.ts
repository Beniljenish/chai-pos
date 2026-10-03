/**
 * Getting a receipt onto paper, per tablet (README, "Printing").
 *
 *   browser   - the browser's print dialog (a PC with a USB printer, or a test)
 *   rawbt     - the free RawBT app on Android, which reaches almost any Bluetooth
 *               thermal printer, including "classic" Bluetooth ones a web page
 *               cannot talk to. We hand it the ESC/POS bytes as a rawbt: link.
 *   bluetooth - straight to a Bluetooth LE printer from the browser (Chrome on
 *               Android). No app needed, but only some cheap printers speak LE.
 *
 * The setting lives on the tablet (each tablet has its own printer).
 */
import type { PosDB } from './db';
import { encode, toBase64, type PaperWidth, type Row } from './escpos';

export type PrinterKind = 'browser' | 'rawbt' | 'bluetooth';

export interface PrinterSettings {
  kind: PrinterKind;
  width: PaperWidth;
  autoPrint: boolean; // print as soon as a bill is saved
}

export const DEFAULT_PRINTER: PrinterSettings = { kind: 'browser', width: 32, autoPrint: true };

export async function loadPrinter(db: PosDB): Promise<PrinterSettings> {
  return { ...DEFAULT_PRINTER, ...((await db.getMeta<Partial<PrinterSettings>>('printer')) ?? {}) };
}

export const savePrinter = (db: PosDB, s: PrinterSettings) => db.setMeta('printer', s);

export function rawbtUrl(bytes: Uint8Array): string {
  return `rawbt:base64,${toBase64(bytes)}`;
}

export class PrintError extends Error {}

export interface PrintEnv {
  browserPrint(): void;
  openUrl(url: string): void;
  bluetoothWrite(bytes: Uint8Array): Promise<void>;
}

/** Send rows to the tablet's printer. Throws PrintError with a plain message. */
export async function printRows(rows: Row[], s: PrinterSettings, env: PrintEnv): Promise<void> {
  if (s.kind === 'browser') return env.browserPrint();
  const bytes = encode(rows);
  if (s.kind === 'rawbt') return env.openUrl(rawbtUrl(bytes));
  return env.bluetoothWrite(bytes);
}

// ---------------------------------------------------------------- Bluetooth LE
// Minimal shapes of the Web Bluetooth API (not in TypeScript's DOM types).
interface BleCharacteristic {
  properties: { write: boolean; writeWithoutResponse: boolean };
  writeValue(data: BufferSource): Promise<void>;
  writeValueWithoutResponse?(data: BufferSource): Promise<void>;
}
interface BleService {
  getCharacteristics(): Promise<BleCharacteristic[]>;
}
interface BleDevice {
  name?: string;
  gatt?: {
    connected: boolean;
    connect(): Promise<{ getPrimaryServices(): Promise<BleService[]> }>;
  };
  addEventListener(type: 'gattserverdisconnected', fn: () => void): void;
}
interface BleNavigator {
  bluetooth?: {
    requestDevice(opts: { acceptAllDevices: boolean; optionalServices: (string | number)[] }): Promise<BleDevice>;
  };
}

// Services cheap BLE thermal printers commonly use for their print channel.
export const PRINTER_SERVICES: (string | number)[] = [
  '000018f0-0000-1000-8000-00805f9b34fb',
  'e7810a71-73ae-499d-8c15-faa9aef0c3f2',
  '49535343-fe7d-4ae5-8fa9-9fafd205e455',
  0xff00,
  0xffe0,
];
const CHUNK = 180; // bytes per write: small enough for any BLE link

let connected: { device: BleDevice; ch: BleCharacteristic } | null = null;

export const bluetoothAvailable = () =>
  typeof navigator !== 'undefined' && Boolean((navigator as unknown as BleNavigator).bluetooth);

export function bluetoothPrinterName(): string | null {
  return connected?.device.name ?? null;
}

/**
 * Pick the printer (the browser shows its own list; needs a tap) and find a
 * channel that takes writes. Remembered until the page reloads or the printer
 * disconnects; then the next print asks again.
 */
export async function connectBluetooth(): Promise<string> {
  const bt = (navigator as unknown as BleNavigator).bluetooth;
  if (!bt) throw new PrintError('This browser cannot reach Bluetooth printers. Use the RawBT app instead.');
  let device: BleDevice;
  try {
    device = await bt.requestDevice({ acceptAllDevices: true, optionalServices: PRINTER_SERVICES });
  } catch {
    throw new PrintError('No printer chosen.');
  }
  if (!device.gatt) throw new PrintError('That device cannot be printed to.');
  const server = await device.gatt.connect();
  for (const service of await server.getPrimaryServices().catch(() => [] as BleService[])) {
    for (const ch of await service.getCharacteristics().catch(() => [] as BleCharacteristic[])) {
      if (ch.properties.write || ch.properties.writeWithoutResponse) {
        connected = { device, ch };
        device.addEventListener('gattserverdisconnected', () => (connected = null));
        return device.name ?? 'printer';
      }
    }
  }
  throw new PrintError(
    `${device.name ?? 'That printer'} has no print channel this app recognises. Use the RawBT app instead.`,
  );
}

export async function bluetoothWrite(bytes: Uint8Array): Promise<void> {
  if (!connected || !connected.device.gatt?.connected) await connectBluetooth();
  const ch = connected!.ch;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const part = bytes.slice(i, i + CHUNK);
    if (ch.properties.writeWithoutResponse && ch.writeValueWithoutResponse) await ch.writeValueWithoutResponse(part);
    else await ch.writeValue(part);
  }
}

/** The real tablet. Under test automation nothing is sent to hardware or apps. */
export const browserEnv: PrintEnv = {
  browserPrint: () => {
    if (!navigator.webdriver) window.print();
  },
  openUrl: (url) => {
    // Lets an end-to-end test see what would have been printed.
    window.dispatchEvent(new CustomEvent('chai-pos:print', { detail: url }));
    if (!navigator.webdriver) window.location.href = url;
  },
  bluetoothWrite,
};
