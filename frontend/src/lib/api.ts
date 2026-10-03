/**
 * API client.
 *
 * Tokens: the short-lived access token lives only in memory (gone when the app
 * closes). The long-lived refresh token is kept in IndexedDB so the tablet stays
 * logged in across restarts, even offline. Trade-off accepted in Phase 2b: script
 * running inside the app could read it, so the app ships a strict CSP and no
 * third-party scripts (see index.html).
 *
 * Errors: NetworkError means "couldn't reach the server, try later" (the outbox
 * keeps the bill). HttpError means "the server answered no" (don't blindly retry).
 */
import type { PosDB } from './db';

export class NetworkError extends Error {}
export class HttpError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(`HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}
export class AuthRequiredError extends HttpError {}

type FetchFn = typeof fetch;
type Tokens = { access_token: string; refresh_token: string };
export interface Reply<T> {
  data: T;
  headers: Headers;
}

export interface ApiOptions {
  baseUrl: string;
  db: PosDB;
  fetchFn?: FetchFn; // injectable so tests can simulate a bad network
}

export class Api {
  private accessToken: string | null = null;
  private refreshing: Promise<boolean> | null = null;
  readonly baseUrl: string;
  private db: PosDB;
  private fetchFn: FetchFn;

  constructor(opts: ApiOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '');
    this.db = opts.db;
    this.fetchFn = opts.fetchFn ?? ((...a) => fetch(...a));
  }

  setFetch(fn: FetchFn) {
    this.fetchFn = fn;
  }

  async login(phone: string, password: string): Promise<void> {
    const { data } = await this.raw('POST', '/auth/login', { phone, password }, false);
    await this.storeTokens(data as Tokens);
  }

  /** Own password. The server ends every other session and returns new tokens. */
  async changePassword(current: string, next: string): Promise<void> {
    const data = await this.post<Tokens>('/auth/password', { current_password: current, new_password: next });
    await this.storeTokens(data);
  }

  async logout(): Promise<void> {
    const refresh = await this.db.getMeta<string>('refreshToken');
    this.accessToken = null;
    await this.db.setMeta('refreshToken', null);
    if (refresh) {
      // Best effort: revoke on the server; fine if we're offline.
      await this.raw('POST', '/auth/logout', { refresh_token: refresh }, false).catch(() => {});
    }
  }

  async hasSession(): Promise<boolean> {
    return Boolean(this.accessToken || (await this.db.getMeta<string>('refreshToken')));
  }

  async get<T>(path: string, headers?: Record<string, string>): Promise<T> {
    return (await this.request<T>('GET', path, undefined, headers)).data;
  }

  /** GET that also returns response headers (e.g. ETag); data is null on 304. */
  getWithHeaders<T>(path: string, headers?: Record<string, string>) {
    return this.request<T>('GET', path, undefined, headers);
  }

  async post<T>(path: string, body: unknown): Promise<T> {
    return (await this.request<T>('POST', path, body)).data;
  }

  async put<T>(path: string, body: unknown): Promise<T> {
    return (await this.request<T>('PUT', path, body)).data;
  }

  async patch<T>(path: string, body: unknown): Promise<T> {
    return (await this.request<T>('PATCH', path, body)).data;
  }

  /** Authenticated request: refreshes the access token once on 401, then retries. */
  async request<T>(
    method: string,
    path: string,
    body?: unknown,
    headers?: Record<string, string>,
  ): Promise<Reply<T>> {
    if (!this.accessToken) await this.refresh();
    try {
      return (await this.raw(method, path, body, true, headers)) as Reply<T>;
    } catch (e) {
      if (e instanceof HttpError && e.status === 401 && (await this.refresh())) {
        return (await this.raw(method, path, body, true, headers)) as Reply<T>;
      }
      throw e;
    }
  }

  /** One refresh at a time, however many requests hit a 401 together. */
  private refresh(): Promise<boolean> {
    if (!this.refreshing) {
      this.refreshing = this.doRefresh().finally(() => {
        this.refreshing = null;
      });
    }
    return this.refreshing;
  }

  private async doRefresh(): Promise<boolean> {
    const refresh = await this.db.getMeta<string>('refreshToken');
    if (!refresh) return false;
    try {
      const { data } = await this.raw('POST', '/auth/refresh', { refresh_token: refresh }, false);
      await this.storeTokens(data as Tokens);
      return true;
    } catch (e) {
      if (e instanceof HttpError && e.status === 401) {
        // Refresh token expired or revoked: a real logout. Bills stay in the outbox.
        this.accessToken = null;
        await this.db.setMeta('refreshToken', null);
        return false;
      }
      throw e; // offline: keep the refresh token for later
    }
  }

  private async storeTokens(t: Tokens) {
    this.accessToken = t.access_token;
    await this.db.setMeta('refreshToken', t.refresh_token);
  }

  private async raw(
    method: string,
    path: string,
    body: unknown,
    auth: boolean,
    extraHeaders: Record<string, string> = {},
  ): Promise<Reply<unknown>> {
    const headers: Record<string, string> = { ...extraHeaders };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth) {
      if (!this.accessToken) throw new AuthRequiredError(401, 'Please log in');
      headers.Authorization = `Bearer ${this.accessToken}`;
    }
    let res: Response;
    try {
      res = await this.fetchFn(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw new NetworkError(e instanceof Error ? e.message : 'Network error');
    }
    if (res.status === 304) return { data: null, headers: res.headers };
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const detail = (data as { detail?: unknown } | null)?.detail ?? data;
      throw res.status === 401 && auth
        ? new AuthRequiredError(401, detail)
        : new HttpError(res.status, detail);
    }
    return { data, headers: res.headers };
  }
}
