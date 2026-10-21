/**
 * The owner's "needs me" counts for Manage (low stock, day-end to approve,
 * khata). Four small reads; one failing leaves that count at zero rather than
 * hiding the others. Refreshes when the tab changes, the app regains focus, and
 * every few minutes. Owners only: the routes are owner-only on the server too.
 */
import { useCallback, useEffect, useState } from 'react';
import { NO_ATTENTION, type Attention } from '../lib/attention';
import { businessDate } from '../lib/billing';
import { shiftDay } from '../lib/sales';
import type { StockRow, WastageRow } from '../lib/types';
import { api } from './apiClient';

const EVERY = 5 * 60 * 1000;

async function read(): Promise<Attention> {
  const today = businessDate(new Date());
  const [stock, khata, wastage, d0, d1] = await Promise.allSettled([
    api.get<StockRow[]>('/stock'),
    api.get<{ customers: unknown[] }>('/reports/khata'),
    api.get<WastageRow[]>('/wastage?pending=true'),
    api.get<{ status: string }>(`/day-counts/${today}/report`),
    api.get<{ status: string }>(`/day-counts/${shiftDay(today, -1)}/report`),
  ]);
  const ok = <T>(r: PromiseSettledResult<T>) => (r.status === 'fulfilled' ? r.value : null);
  const submitted = [ok(d0), ok(d1)].filter((r) => r?.status === 'submitted').length;
  return {
    lowStock: (ok(stock) ?? []).filter((r) => r.is_active && (r.below_reorder || r.is_negative)).length,
    owing: ok(khata)?.customers.length ?? 0,
    toApprove: (ok(wastage)?.length ?? 0) + submitted,
  };
}

export function useAttention(enabled: boolean, refreshKey: string): Attention {
  const [value, setValue] = useState<Attention>(NO_ATTENTION);
  const load = useCallback(async () => {
    if (enabled) setValue(await read());
  }, [enabled]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => void load(), EVERY);
    const onFocus = () => void load();
    window.addEventListener('focus', onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [enabled, load]);

  return value;
}
