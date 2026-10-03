/** Owner-only: the shop's records. More sections (Shop & GST) join this list. */
import { useState } from 'react';
import { RecipesScreen } from './RecipesScreen';
import { StockScreen } from './StockScreen';

type Section = 'stock' | 'recipes';
const SECTIONS: { id: Section; label: string }[] = [
  { id: 'stock', label: 'Stock' },
  { id: 'recipes', label: 'Recipes' },
];

export function ManageScreen() {
  const [section, setSection] = useState<Section>('stock');
  return (
    <main className="manage">
      <nav className="subnav" aria-label="Manage">
        {SECTIONS.map((s) => (
          <button key={s.id} aria-pressed={section === s.id} onClick={() => setSection(s.id)}>
            {s.label}
          </button>
        ))}
      </nav>
      {section === 'stock' ? <StockScreen /> : <RecipesScreen />}
    </main>
  );
}
