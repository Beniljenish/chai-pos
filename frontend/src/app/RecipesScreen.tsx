/** Owner's SOPs: what every drink and every batch uses, plus the ingredient list. */
import { useCallback, useEffect, useState } from 'react';
import { formatQty, type BaseUnit } from '../lib/qty';
import type { Catalogue, Ingredient, Recipe, RecipeLine } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { IngredientsPanel } from './IngredientsPanel';
import { MenuItemEditor } from './MenuPrices';
import { OptionsPanel } from './OptionsPanel';
import { RecipeEditor, type RecipeTarget } from './RecipeEditor';
import { useSession } from './session';

type MenuRow = Catalogue['menu_items'][number];

const summary = (r: { lines: RecipeLine[] } | null) =>
  r && r.lines.length
    ? r.lines.map((l) => `${l.ingredient_name} ${formatQty(l.qty, l.base_unit as BaseUnit)}`).join(' · ')
    : null;

export function RecipesScreen() {
  const { reloadCatalogue } = useSession();
  const [menu, setMenu] = useState<MenuRow[] | null>(null);
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [prepRecipes, setPrepRecipes] = useState<Record<string, Recipe | null>>({});
  const [editing, setEditing] = useState<RecipeTarget | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      // Fresh catalogue straight from the server (not the device's cached copy).
      const [cat, ings] = await Promise.all([api.get<Catalogue>('/catalogue'), api.get<Ingredient[]>('/ingredients')]);
      setMenu(cat.menu_items);
      setIngredients(ings);
      const preps = ings.filter((i) => i.kind === 'prep');
      const recipes = await Promise.all(preps.map((p) => api.get<Recipe | null>(`/ingredients/${p.id}/recipe`)));
      setPrepRecipes(Object.fromEntries(preps.map((p, i) => [p.id, recipes[i]])));
      setError(null);
    } catch (e) {
      setError(explainError(e));
      setMenu((m) => m ?? []);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const categories = [...new Set((menu ?? []).map((m) => m.category))];
  const preps = ingredients.filter((i) => i.kind === 'prep' && i.is_active);

  return (
    <section className="recipes">
      <header className="manage-head">
        <h1>Recipes</h1>
        <button className="primary" onClick={() => setAdding(true)}>
          + New drink
        </button>
      </header>
      <p className="muted">
        The SOP for every drink: what one serving takes out of stock. Changing a recipe makes a new version; old bills
        keep theirs.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {menu === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          {categories.map((c) => (
            <div key={c}>
              <h2>{c}</h2>
              <ul className="sop-list">
                {menu
                  .filter((m) => m.category === c)
                  .map((m) => {
                    const s = summary(m.recipe);
                    return (
                      <li key={m.id}>
                        <button onClick={() => setEditing({ kind: 'menu', id: m.id, name: m.name })}>
                          <span className="sop-name">
                            <strong>{m.name}</strong>
                            {m.recipe && <span className="muted"> v{m.recipe.version}</span>}
                          </span>
                          <span className={s ? 'sop-lines' : 'sop-lines warn-text'}>
                            {s ?? 'No recipe: sales do not reduce stock'}
                          </span>
                        </button>
                      </li>
                    );
                  })}
              </ul>
            </div>
          ))}

          <OptionsPanel menu={menu} ingredients={ingredients} onChanged={() => void reloadCatalogue()} />

          {preps.length > 0 && (
            <>
              <h2>Made here (batches)</h2>
              <ul className="sop-list">
                {preps.map((p) => {
                  const r = prepRecipes[p.id] ?? null;
                  const s = summary(r);
                  return (
                    <li key={p.id}>
                      <button onClick={() => setEditing({ kind: 'prep', id: p.id, name: p.name, unit: p.base_unit })}>
                        <span className="sop-name">
                          <strong>{p.name}</strong>
                          {r && <span className="muted"> v{r.version}</span>}
                        </span>
                        <span className={s ? 'sop-lines' : 'sop-lines warn-text'}>
                          {s ? `${s} → makes ${formatQty(r!.yield_qty ?? 0, p.base_unit)}` : 'No batch recipe yet'}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          <IngredientsPanel ingredients={ingredients} onChanged={() => void load()} />
        </>
      )}

      {adding && (
        <MenuItemEditor
          item={null}
          categories={categories}
          defaultCategory={categories[0]}
          recipeNext
          onClose={() => setAdding(false)}
          onSaved={(item) => {
            setAdding(false);
            void load();
            void reloadCatalogue();
            setEditing({ kind: 'menu', id: item.id, name: item.name });
          }}
        />
      )}

      {editing && (
        <RecipeEditor
          target={editing}
          ingredients={ingredients}
          onClose={() => setEditing(null)}
          onSaved={() => {
            void load();
            void reloadCatalogue(); // this tablet bills with the new version straight away
          }}
        />
      )}
    </section>
  );
}
