/** Staff attendance and the pay sheet (README, "9.21"): types, wording and the CSV. */
import { csvRupees } from './reports';

export interface AttendanceEntry {
  id: string;
  user_id: string;
  date: string;
  clock_in_at: string;
  clock_out_at: string | null;
  minutes: number | null;
  note: string;
  edited: boolean;
  too_long: boolean;
}

export interface AttendancePerson {
  user_id: string;
  name: string;
  minutes: number;
  still_in: boolean;
  rate_paise: number | null;
  pay_paise: number | null;
  entries: AttendanceEntry[];
}

export interface AttendanceReport {
  from: string;
  to: string;
  people: AttendancePerson[];
}

/** 2480 -> "41 h 20 m"; under an hour "35 m". */
export function hm(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h === 0 ? `${m} m` : `${h} h ${String(m).padStart(2, '0')} m`;
}

const clock = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }).format(
    new Date(iso),
  );

/** The sheet as spreadsheet rows: a line per entry with each person's total after it. */
export function attendanceRows(r: AttendanceReport): (string | number)[][] {
  const rows: (string | number)[][] = [['Person', 'Date', 'In', 'Out', 'Minutes', 'Note']];
  for (const p of r.people) {
    for (const e of p.entries) {
      rows.push([p.name, e.date, clock(e.clock_in_at), e.clock_out_at ? clock(e.clock_out_at) : 'still in', e.minutes ?? '', e.note]);
    }
    rows.push([`${p.name} total`, '', '', '', p.minutes, p.pay_paise === null ? 'no rate set' : `pay ${csvRupees(p.pay_paise)}`]);
  }
  return rows;
}

/** "₹123.45" typed -> paise (0 clears the rate); null when it is not an amount. */
export function rateToPaise(text: string): number | null {
  const m = /^(\d{1,5})(?:\.(\d{1,2}))?$/.exec(text.trim());
  return m ? Number(m[1]) * 100 + Number((m[2] ?? '').padEnd(2, '0')) : null;
}
