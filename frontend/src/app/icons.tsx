/** Line icons (24 px grid, drawn with the text colour). Always decorative:
 * the button or link they sit in is named by its words. */
export const ICON = {
  bill: 'M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6',
  tables: 'M3 8h18v4H3zM6 12v8M18 12v8',
  today: 'M4 5h16v16H4zM4 10h16M9 3v4M15 3v4',
  manage: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  sales: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  reports: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
  khata: 'M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h11M9 8h6',
  stock: 'M3 7l9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10',
  purchases: 'M3 4h2l2.5 11h11L21 7H6.2M9 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM18 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  dayend: 'M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9',
  recipes: 'M4 11h16a8 8 0 0 1-16 0zM8 7c0-1.5 1-2 1-3.5M12 7c0-1.5 1-2 1-3.5M16 7c0-1.5 1-2 1-3.5',
  shop: 'M3 9l1.5-5h15L21 9M3 9v11h18V9M3 9h18M9 20v-6h6v6',
  staff: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21v-1a6 6 0 0 1 12 0v1M16 3.5a4 4 0 0 1 0 7M22 21v-1a6 6 0 0 0-4-5.6',
  floor: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  tablets: 'M6 2h12a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM11 18h2',
  messages: 'M4 4h16v12H8l-4 4zM8 9h8M8 12h5',
  logout: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10',
  cash: 'M3 7h18v10H3zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  upi: 'M7 3h10v18H7zM11 18h2',
  card: 'M3 6h18v12H3zM3 10h18',
  split: 'M6 3v6a6 6 0 0 0 6 6 6 6 0 0 1 6 6M18 3v6a6 6 0 0 1-3 5.2M3 6l3-3 3 3M15 6l3-3 3 3',
  credit: 'M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h11',
  print: 'M6 9V3h12v6M6 18H4v-7h16v7h-2M8 14h8v7H8z',
  tag: 'M3 12V4h8l10 10-8 8zM7.5 7.5h.01',
  user: 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0',
} as const;

export type IconName = keyof typeof ICON;

export function Icon({ name, size = 22 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICON[name]} />
    </svg>
  );
}
