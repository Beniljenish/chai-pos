/** "3 packets + 200 ml": how staff count and receive stock. */
import { formatQty, packsToBase } from '../lib/qty';
import type { Ingredient } from '../lib/types';

interface Props {
  ingredient: Ingredient;
  counts: Record<string, number>;
  loose: string;
  onCounts(next: Record<string, number>): void;
  onLoose(next: string): void;
}

export function PackEntry({ ingredient, counts, loose, onCounts, onLoose }: Props) {
  const unit = ingredient.base_unit;
  const total = packsToBase(ingredient.pack_units, counts, Number(loose) || 0);
  const set = (id: string, n: number) => onCounts({ ...counts, [id]: Math.max(0, n) });

  return (
    <div className="pack-entry">
      {ingredient.pack_units.map((u) => (
        <div className="pack-row" key={u.id}>
          <span>
            <strong>{u.name}</strong>
            <span className="muted"> ({formatQty(u.qty_in_base, unit)})</span>
          </span>
          <div className="stepper">
            <button aria-label={`One ${u.name} less`} onClick={() => set(u.id, (counts[u.id] ?? 0) - 1)}>
              −
            </button>
            <span className="num" aria-live="polite">
              {counts[u.id] ?? 0}
            </span>
            <button aria-label={`One ${u.name} more`} onClick={() => set(u.id, (counts[u.id] ?? 0) + 1)}>
              +
            </button>
          </div>
        </div>
      ))}
      <label className="loose">
        {ingredient.pack_units.length ? `Loose (${unit === 'piece' ? 'pieces' : unit})` : `Quantity (${unit === 'piece' ? 'pieces' : unit})`}
        <input
          inputMode="decimal"
          value={loose}
          onChange={(e) => onLoose(e.target.value.replace(/[^0-9.]/g, ''))}
          placeholder="0"
        />
      </label>
      <p className="pack-total">
        Total <strong className="num">{formatQty(total, unit)}</strong>
      </p>
    </div>
  );
}
