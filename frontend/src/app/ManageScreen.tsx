/** Owner-only: the shop's records. */
import { useState } from 'react';
import { DayEndScreen } from './DayEndScreen';
import { FloorSetup } from './FloorSetup';
import { PurchasesScreen } from './PurchasesScreen';
import { ReportsScreen } from './ReportsScreen';
import { RecipesScreen } from './RecipesScreen';
import { SalesScreen } from './SalesScreen';
import { ShopScreen } from './ShopScreen';
import { StaffScreen } from './StaffScreen';
import { TabletsScreen } from './TabletsScreen';
import { StockScreen } from './StockScreen';

type Section = 'sales' | 'stock' | 'dayend' | 'recipes' | 'shop' | 'staff' | 'tablets' | 'floor' | 'reports' | 'purchases';
const SECTIONS: { id: Section; label: string }[] = [
  { id: 'sales', label: 'Sales' },
  { id: 'reports', label: 'Reports' },
  { id: 'stock', label: 'Stock' },
  { id: 'purchases', label: 'Purchases' },
  { id: 'dayend', label: 'Day end' },
  { id: 'recipes', label: 'Recipes' },
  { id: 'shop', label: 'Shop & GST' },
  { id: 'floor', label: 'Floor' },
  { id: 'staff', label: 'Staff' },
  { id: 'tablets', label: 'Tablets' },
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
      ) : section === 'reports' ? (
        <ReportsScreen />
      ) : section === 'purchases' ? (
        <PurchasesScreen />
      ) : section === 'stock' ? (
        <StockScreen />
      ) : section === 'dayend' ? (
        <DayEndScreen />
      ) : section === 'recipes' ? (
        <RecipesScreen />
      ) : section === 'shop' ? (
        <ShopScreen />
      ) : section === 'floor' ? (
        <FloorSetup />
      ) : section === 'staff' ? (
        <StaffScreen />
      ) : (
        <TabletsScreen />
      )}
    </main>
  );
}
