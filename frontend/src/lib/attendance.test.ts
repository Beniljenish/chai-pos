import { describe, expect, it } from 'vitest';
import { attendanceRows, hm, rateToPaise, type AttendanceReport } from './attendance';

describe('attendance', () => {
  it('writes hours and minutes', () => {
    expect(hm(2480)).toBe('41 h 20 m');
    expect(hm(35)).toBe('35 m');
    expect(hm(61)).toBe('1 h 01 m');
    expect(hm(0)).toBe('0 m');
  });

  it('reads a typed hourly rate in paise', () => {
    expect(rateToPaise('123.45')).toBe(12345);
    expect(rateToPaise('50')).toBe(5000);
    expect(rateToPaise('0')).toBe(0);
    expect(rateToPaise('abc')).toBeNull();
    expect(rateToPaise('12.345')).toBeNull();
  });

  it('puts each person total and pay after their entries', () => {
    const r: AttendanceReport = {
      from: '2026-10-19',
      to: '2026-10-25',
      people: [
        {
          user_id: 'u1',
          name: 'Ravi',
          minutes: 510,
          still_in: false,
          rate_paise: 12345,
          pay_paise: 104933,
          entries: [
            { id: 'e1', user_id: 'u1', date: '2026-10-20', clock_in_at: '2026-10-20T03:30:00Z', clock_out_at: '2026-10-20T12:00:00Z', minutes: 510, note: '', edited: false, too_long: false },
          ],
        },
      ],
    };
    const rows = attendanceRows(r);
    expect(rows[1]).toEqual(['Ravi', '2026-10-20', '09:00', '17:30', 510, '']);
    expect(rows[2]).toEqual(['Ravi total', '', '', '', 510, 'pay 1049.33']);
  });
});
