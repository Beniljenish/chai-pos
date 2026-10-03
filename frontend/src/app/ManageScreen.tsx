/** Owner-only: the shop's records. */
import { useState } from 'react';
import { DayEndScreen } from './DayEndScreen';
import { RecipesScreen } from './RecipesScreen';
import { SalesScreen } from './SalesScreen';
import { ShopScreen } from './ShopScreen';
import { StaffScreen } from './StaffScreen';
import { StockScreen } from './StockScreen';

type Section = 'sales' | 'stock' | 'dayend' | 'recipes' | 'shop' | 'staff';
const SECTIONS: { id: Section; label: string }[] = [
  { id: 'sales', label: 'Sales' },
  { id: 'stock', label: 'Stock' },
  { id: 'dayend', label: 'Day end' },
  { id: 'recipes', label: 'Recipes' },
  { id: 'shop', label: 'Shop & GST' },
  { id: 'staff', label: 'Staff' },
];

export function ManageScreen() {
  const [section, setSection] = useState<Section>('sales');
  return (
    <main className="manage">
      <nav className="subnav" aria-label="Manage">
        {SECTIONS.map((s) => (
          <button key={s.id} aria-pressed={section === s.id} onClick={() => setSection(s.id)}>
            {s.label}
          </button>
        ))}
      </nav>
      {section === 'sales' ? (
        <SalesScreen />
      ) : section === 'stock' ? (
        <StockScreen />
      ) : section === 'dayend' ? (
        <DayEndScreen />
      ) : section === 'recipes' ? (
        <RecipesScreen />
      ) : section === 'shop' ? (
        <ShopScreen />
      ) : (
        <StaffScreen />
      )}
    </main>
  );
}
