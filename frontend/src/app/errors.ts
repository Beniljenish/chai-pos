import { HttpError, NetworkError } from '../lib/api';

/** One plain sentence for any failed owner action. */
export function explainError(e: unknown): string {
  if (e instanceof NetworkError) return 'No internet. This needs a connection; try again when you are online.';
  if (e instanceof HttpError) {
    const d = e.detail as unknown;
    if (typeof d === 'string') return d;
    if (d && typeof d === 'object' && 'message' in d) return String((d as { message: unknown }).message);
    if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg);
    if (e.status === 403) return 'Only the owner can do this.';
  }
  return 'Something went wrong. Try again.';
}
