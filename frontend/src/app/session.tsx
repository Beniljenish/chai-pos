/**
 * The app's session: who is logged in, which tablet this is, the menu, and the
 * sync worker. Everything here also works offline from what was saved before.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { NetworkError } from '../lib/api';
import { api } from './apiClient';
import { resumeCounters } from '../lib/billing';
import { loadCachedCatalogue, refreshCatalogue } from '../lib/catalogue';
import { db, requestPersistentStorage } from '../lib/db';
import { SyncWorker, type SyncState } from '../lib/sync';
import type { Catalogue, Device, User } from '../lib/types';


type Phase = 'loading' | 'login' | 'device' | 'ready';

interface Session {
  phase: Phase;
  user: User | null;
  device: Device | null;
  catalogue: Catalogue | null;
  sync: SyncState | null;
  worker: SyncWorker | null;
  notice: string | null;
  login(phone: string, password: string): Promise<void>;
  logout(): Promise<void>;
  chooseDevice(device: Device): Promise<void>;
  reloadCatalogue(): Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error('useSession outside SessionProvider');
  return s;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [device, setDevice] = useState<Device | null>(null);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [worker, setWorker] = useState<SyncWorker | null>(null);
  const [sync, setSync] = useState<SyncState | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  /** Online extras: fresh menu, counter resume. Silently skipped when offline. */
  const refreshFromServer = useCallback(async (dev: Device) => {
    try {
      const fresh = await refreshCatalogue(api, db);
      if (fresh) setCatalogue(fresh);
      const state = await api.get<{ last_seq_by_fy: Record<string, number>; is_active: boolean }>(
        `/devices/${dev.id}/sync-state`,
      );
      await resumeCounters(db, dev.id, state.last_seq_by_fy);
      setNotice(state.is_active ? null : 'The owner has switched this tablet off. Bills cannot be sent.');
    } catch (e) {
      if (!(e instanceof NetworkError)) throw e;
    }
  }, []);

  const enterReady = useCallback(
    async (dev: Device) => {
      setDevice(dev);
      setCatalogue(await loadCachedCatalogue(db));
      setPhase('ready');
      void requestPersistentStorage();
      await refreshFromServer(dev).catch(() => {});
    },
    [refreshFromServer],
  );

  // Boot: works from local data alone, so the app opens offline.
  useEffect(() => {
    (async () => {
      const savedUser = await db.getMeta<User>('user');
      const savedDevice = await db.getMeta<Device>('device');
      if (!savedUser || !(await api.hasSession())) return setPhase('login');
      setUser(savedUser);
      if (!savedDevice) return setPhase('device');
      await enterReady(savedDevice);
    })();
  }, [enterReady]);

  // One sync worker per registered tablet.
  useEffect(() => {
    if (phase !== 'ready' || !device) return;
    const w = new SyncWorker(api, db, device.id);
    setWorker(w);
    const unsub = w.subscribe(setSync);
    w.start();
    return () => {
      unsub();
      w.stop();
    };
  }, [phase, device]);

  const login = useCallback(
    async (phone: string, password: string) => {
      await api.login(phone, password);
      const me = await api.get<User>('/auth/me');
      await db.setMeta('user', me);
      setUser(me);
      const savedDevice = await db.getMeta<Device>('device');
      if (savedDevice) await enterReady(savedDevice);
      else setPhase('device');
    },
    [enterReady],
  );

  const logout = useCallback(async () => {
    // The tablet's identity, menu and unsent bills stay: only the person logs out.
    await api.logout();
    await db.setMeta('user', null);
    setUser(null);
    setPhase('login');
  }, []);

  const chooseDevice = useCallback(
    async (dev: Device) => {
      await db.setMeta('device', dev);
      await enterReady(dev);
    },
    [enterReady],
  );

  const reloadCatalogue = useCallback(async () => {
    if (device) await refreshFromServer(device);
  }, [device, refreshFromServer]);

  const value = useMemo<Session>(
    () => ({ phase, user, device, catalogue, sync, worker, notice, login, logout, chooseDevice, reloadCatalogue }),
    [phase, user, device, catalogue, sync, worker, notice, login, logout, chooseDevice, reloadCatalogue],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
