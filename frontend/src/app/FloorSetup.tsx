/**
 * Owner: the dining floor. Areas (Hall, AC room, Outdoor) and their tables.
 * Bulk add makes setting up a 20-table restaurant a minute's work.
 */
import { useCallback, useEffect, useState } from 'react';
import { nextNames } from '../lib/floor';
import { api } from './apiClient';
import { Loading, LoadError } from './Status';
import { explainError } from './errors';
import { Sheet } from './Sheet';
import { useSession } from './session';

interface Table {
  id: string;
  name: string;
  seats: number;
  sort: number;
  is_active: boolean;
}
interface Area {
  id: string;
  name: string;
  sort: number;
  is_active: boolean;
  tables: Table[];
}

export function FloorSetup() {
  const { reloadCatalogue } = useSession();
  const [areas, setAreas] = useState<Area[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<{ kind: 'area' } | { kind: 'add'; area: Area } | { kind: 'table'; area: Area; table: Table } | null>(null);

  const load = useCallback(async () => {
    try {
      setAreas(await api.get<Area[]>('/dining'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const changed = () => {
    void load();
    void reloadCatalogue(); // this tablet sees the new tables straight away
  };

  const allNames = (areas ?? []).flatMap((a) => a.tables.map((t) => t.name));

  return (
    <section className="floor-setup">
      <header className="manage-head">
        <h1>Floor</h1>
        <button className="primary" onClick={() => setSheet({ kind: 'area' })}>
          + Area
        </button>
      </header>
      <p className="muted">
        Areas and tables for table service. Tables appear on every tablet&apos;s Tables screen; switching one off hides it
        without losing its history.
      </p>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {areas === null && !error && <Loading />}
      {areas?.length === 0 && (
        <div className="empty-card">
          <p>
            <strong>No tables yet.</strong> Add an area (for example &quot;Hall&quot;), then add its tables. A counter-only
            tea shop can skip this: quick billing works without tables.
          </p>
        </div>
      )}
      {(areas ?? []).map((a) => (
        <div key={a.id} className={`area-card ${a.is_active ? '' : 'off'}`}>
          <div className="shift-head">
            <h2>{a.name}</h2>
            <span className="muted">
              {a.tables.filter((t) => t.is_active).length} tables · {a.tables.filter((t) => t.is_active).reduce((n, t) => n + t.seats, 0)}{' '}
              seats
            </span>
          </div>
          <ul className="table-chips">
            {a.tables.map((t) => (
              <li key={t.id}>
                <button className={t.is_active ? '' : 'off'} onClick={() => setSheet({ kind: 'table', area: a, table: t })}>
                  <strong>{t.name}</strong>
                  <span className="muted">{t.seats} seats</span>
                </button>
              </li>
            ))}
            <li>
              <button className="add" onClick={() => setSheet({ kind: 'add', area: a })} aria-label={`Add tables to ${a.name}`}>
                + Tables
              </button>
            </li>
          </ul>
        </div>
      ))}

      {sheet?.kind === 'area' && <AreaSheet onClose={() => setSheet(null)} onDone={changed} />}
      {sheet?.kind === 'add' && (
        <AddTablesSheet area={sheet.area} allNames={allNames} onClose={() => setSheet(null)} onDone={changed} />
      )}
      {sheet?.kind === 'table' && (
        <TableSheet area={sheet.area} table={sheet.table} areas={areas ?? []} onClose={() => setSheet(null)} onDone={changed} />
      )}
    </section>
  );
}

function AreaSheet({ onClose, onDone }: { onClose(): void; onDone(): void }) {
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  async function save() {
    try {
      await api.post('/areas', { name: name.trim() });
      onDone();
      onClose();
    } catch (e) {
      setError(explainError(e));
    }
  }
  return (
    <Sheet title="New area" onClose={onClose}>
      <label>
        Name
        <input value={name} maxLength={40} placeholder="Hall" autoFocus onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="chips" role="group" aria-label="Common names">
        {['Hall', 'AC room', 'Outdoor', 'Family', 'Counter'].map((n) => (
          <button key={n} className="chip" aria-pressed={name === n} onClick={() => setName(n)}>
            {n}
          </button>
        ))}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="sheet-actions">
        <button className="primary" disabled={!name.trim()} onClick={() => void save()}>
          Add area
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Sheet>
  );
}

function AddTablesSheet({ area, allNames, onClose, onDone }: { area: Area; allNames: string[]; onClose(): void; onDone(): void }) {
  const [count, setCount] = useState('4');
  const [prefix, setPrefix] = useState(area.tables.length ? area.tables[0].name.replace(/\d+$/, '') || 'T' : 'T');
  const [seats, setSeats] = useState('4');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const n = Math.min(50, Math.max(0, Number(count) || 0));
  const names = nextNames(allNames, n, prefix.trim());

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const base = area.tables.length;
      for (const [i, name] of names.entries()) {
        await api.post('/tables', { area_id: area.id, name, seats: Number(seats) || 4, sort: base + i });
      }
      onDone();
      onClose();
    } catch (e) {
      setError(explainError(e));
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={`Add tables to ${area.name}`} onClose={onClose}>
      <div className="form-row">
        <label>
          How many
          <input inputMode="numeric" value={count} onChange={(e) => setCount(e.target.value.replace(/\D/g, ''))} />
        </label>
        <label>
          Name starts with
          <input value={prefix} maxLength={10} onChange={(e) => setPrefix(e.target.value)} />
        </label>
        <label>
          Seats each
          <input inputMode="numeric" value={seats} onChange={(e) => setSeats(e.target.value.replace(/\D/g, ''))} />
        </label>
      </div>
      {names.length > 0 && <p className="muted">Will add: {names.join(', ')}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="sheet-actions">
        <button className="primary" disabled={busy || names.length === 0} onClick={() => void add()}>
          Add {names.length} table{names.length === 1 ? '' : 's'}
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Sheet>
  );
}

function TableSheet({
  area,
  table,
  areas,
  onClose,
  onDone,
}: {
  area: Area;
  table: Table;
  areas: Area[];
  onClose(): void;
  onDone(): void;
}) {
  const [name, setName] = useState(table.name);
  const [seats, setSeats] = useState(String(table.seats));
  const [areaId, setAreaId] = useState(area.id);
  const [error, setError] = useState<string | null>(null);

  async function save(patch: Record<string, unknown>) {
    try {
      await api.patch(`/tables/${table.id}`, patch);
      onDone();
      onClose();
    } catch (e) {
      setError(explainError(e));
    }
  }

  return (
    <Sheet title={`Table ${table.name}`} onClose={onClose}>
      <div className="form-row">
        <label>
          Name
          <input value={name} maxLength={20} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Seats
          <input inputMode="numeric" value={seats} onChange={(e) => setSeats(e.target.value.replace(/\D/g, ''))} />
        </label>
      </div>
      <label>
        Area
        <select value={areaId} onChange={(e) => setAreaId(e.target.value)}>
          {areas.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="sheet-actions">
        <button
          className="primary"
          disabled={!name.trim() || !(Number(seats) > 0)}
          onClick={() => void save({ name: name.trim(), seats: Number(seats), area_id: areaId })}
        >
          Save
        </button>
        {table.is_active ? (
          <button onClick={() => void save({ is_active: false })}>Switch off</button>
        ) : (
          <button onClick={() => void save({ is_active: true })}>Switch on</button>
        )}
      </div>
    </Sheet>
  );
}
