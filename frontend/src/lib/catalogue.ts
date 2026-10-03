/** The menu, cached on the tablet. Downloaded with an ETag: unchanged = tiny 304. */
import type { Api } from './api';
import type { PosDB } from './db';
import type { Catalogue } from './types';

export async function loadCachedCatalogue(db: PosDB): Promise<Catalogue | null> {
  return (await db.catalogue.get('current'))?.data ?? null;
}

/** Returns the freshest catalogue available: from the server if reachable, else cached. */
export async function refreshCatalogue(api: Api, db: PosDB): Promise<Catalogue | null> {
  const cached = await db.catalogue.get('current');
  const headers: Record<string, string> = cached?.etag ? { 'If-None-Match': cached.etag } : {};
  const reply = await api.getWithHeaders<Catalogue | null>('/catalogue', headers);
  if (reply.data === null && cached) return cached.data; // 304: nothing changed
  if (reply.data) {
    await db.catalogue.put({
      key: 'current',
      etag: reply.headers.get('ETag'),
      data: reply.data,
      fetchedAt: new Date().toISOString(),
    });
  }
  return reply.data ?? cached?.data ?? null;
}
