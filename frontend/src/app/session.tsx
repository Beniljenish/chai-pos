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
import {
  adoptServerState,
  currentShift,
  lastCount,
  type LastCount,
  type LocalShift,
  type ServerShiftState,
} from '../lib/shift';
import { SyncWorker, type SyncState } from '../lib/sync';
import type { Catalogue, Device, User } from '../lib/types';


type Phase = 'loading' | 'login' | 'password' | 'device' | 'ready';

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
  /** Own password; also how someone with an owner-set password gets past 'password'. */
  changePassword(current: string, next: string): Promise<void>;
  /** The drawer shift open on this tablet (null: none), and the last count. */
  shift: LocalShift | null;
  lastCounted: LastCount | null;
  reloadShift(): Promise<void>;
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
  const [shift, setShift] = useState<LocalShift | null>(null);
  const [lastCounted, setLastCounted] = useState<LastCount | null>(null);

  const reloadShift = useCallback(async () => {
    setShift((await currentShift(db)) ?? null);
    setLastCounted((await lastCount(db)) ?? null);
  }, []);

  /** Online extras: fresh menu, counter resume. Silently skipped when offline. */
  const refreshFromServer = useCallback(async (dev: Device) => {
    try {
      const fresh = await refreshCatalogue(api, db);
      if (fresh) setCatalogue(fresh);
      const state = await api.get<
        { last_seq_by_fy: Record<string, number>; is_active: boolean } & Partial<ServerShiftState>
      >(`/devices/${dev.id}/sync-state`);
      await resumeCounters(db, dev.id, state.last_seq_by_fy);
      if (state.open_shift !== undefined) {
        await adoptServerState(db, { open_shift: state.open_shift, last_counted: state.last_counted ?? null });
        await reloadShift();
      }
      setNotice(state.is_active ? null : 'The owner has switched this tablet off. Bills cannot be sent.');
    } catch (e) {
      if (!(e instanceof NetworkError)) throw e;
    }
  }, [reloadShift]);

  const enterReady = useCallback(
    async (dev: Device) => {
      setDevice(dev);
      setCatalogue(await loadCachedCatalogue(db));
      await reloadShift();
      setPhase('ready');
      void requestPersistentStorage();
      await refreshFromServer(dev).catch(() => {});
    },
    [refreshFromServer, reloadShift],
  );

  // Boot: works from local data alone, so the app opens offline.
  useEffect(() => {
    (async () => {
      const savedUser = await db.getMeta<User>('user');
      const savedDevice = await db.getMeta<Device>('device');
      if (!savedUser || !(await api.hasSession())) return setPhase('login');
      setUser(savedUser);
      if (savedUser.must_change_password) return setPhase('password');
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
      // The owner set this password: the server refuses everything else until
      // the person picks their own, so ask for it before anything else.
      if (me.must_change_password) return setPhase('password');
      const savedDevice = await db.getMeta<Device>('device');
      if (savedDevice) await enterReady(savedDevice);
      else setPhase('device');
    },
    [enterReady],
  );

  const changePassword = useCallback(
    async (current: string, next: string) => {
      await api.changePassword(current, next);
      const me = await api.get<User>('/auth/me');
      await db.setMeta('user', me);
      setUser(me);
      if (phase === 'password') {
        const savedDevice = await db.getMeta<Device>('device');
        if (savedDevice) await enterReady(savedDevice);
        else setPhase('device');
      }
    },
    [phase, enterReady],
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
    () => ({
      phase,
      user,
      device,
      catalogue,
      sync,
      worker,
      notice,
      login,
      logout,
      chooseDevice,
      reloadCatalogue,
      changePassword,
      shift,
      lastCounted,
      reloadShift,
    }),
    [
      phase,
      user,
      device,
      catalogue,
      sync,
      worker,
      notice,
      login,
      logout,
      chooseDevice,
      reloadCatalogue,
      changePassword,
      shift,
      lastCounted,
      reloadShift,
    ],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
