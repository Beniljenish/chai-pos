import { afterEach, describe, expect, it, vi } from 'vitest';

describe('reportError', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('sends each error once, at most five per page, path only, and never throws', async () => {
    const sent: { message: string; place: string }[] = [];
    vi.stubGlobal('fetch', (_url: string, init: RequestInit) => {
      sent.push(JSON.parse(String(init.body)));
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    const { reportError } = await import('./reportError');
    reportError(new Error('boom'), 'screen');
    reportError(new Error('boom'), 'screen'); // the same one: not again
    for (let i = 0; i < 10; i++) reportError(new Error(`other ${i}`));
    expect(sent).toHaveLength(5);
    expect(sent[0].message).toBe('Error: boom');
    expect(sent[0].place).not.toContain('?');

    vi.stubGlobal('fetch', () => {
      throw new Error('network down');
    });
    expect(() => reportError(new Error('late'))).not.toThrow();
  });
});
