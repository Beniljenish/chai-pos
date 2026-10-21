import { useEffect, useState } from 'react';
import type { AiStatus } from '../lib/aiTypes';
import { api } from './apiClient';

/** Whether the AI helpers are switched on, and how many calls are left today. null = still asking. */
export function useAiStatus(refreshKey = 0): AiStatus | null {
  const [status, setStatus] = useState<AiStatus | null>(null);
  useEffect(() => {
    let live = true;
    api
      .get<AiStatus>('/ai/status')
      .then((s) => live && setStatus(s))
      .catch(() => live && setStatus({ on: false, pretend: false, used_today: 0, daily_limit: 0 }));
    return () => void (live = false);
  }, [refreshKey]);
  return status;
}
