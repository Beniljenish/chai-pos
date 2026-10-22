/**
 * The food court's display board (README, "9.17"): ready tokens, big, and the ones being made.
 * Opens from a link on a TV or tablet, no login, and shows tokens and outlet names only.
 * Browsers refuse to speak until someone taps, so sound starts with one tap.
 */
import { useEffect, useRef, useState } from 'react';
import { calls, newlyReady } from '../lib/board';
import { type Board, publicApi } from '../lib/publicApi';
import { hasVoice, speak } from '../lib/voice';
import type { Lang } from '../lib/i18n';

const POLL_MS = 4_000;

export function BoardApp({ slug }: { slug: string }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [failed, setFailed] = useState(false);
  const [sound, setSound] = useState(false);
  const seen = useRef<string[] | null>(null);
  const soundRef = useRef(false);
  soundRef.current = sound;

  useEffect(() => {
    let live = true;
    async function look() {
      try {
        const b = await publicApi.board(slug);
        if (!live) return;
        setBoard(b);
        setFailed(false);
        const tokens = b.ready.map((r) => r.token);
        const fresh = newlyReady(seen.current, tokens);
        seen.current = tokens;
        if (soundRef.current) {
          const langs: Lang[] = hasVoice('ta') ? ['en', 'ta'] : ['en'];
          fresh.forEach((tk) => calls(tk, langs).forEach((c) => speak(c.text, c.lang)));
        }
      } catch {
        if (live) setFailed(true);
      }
    }
    void look();
    const id = setInterval(() => void look(), POLL_MS);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [slug]);

  return (
    <main className="board">
      <header>
        <h1>{board ? `${board.court} · ` : ''}Now serving</h1>
        <button className="quiet" aria-pressed={sound} onClick={() => setSound(!sound)}>
          {sound ? '🔊 Sound on' : '🔇 Tap to turn sound on'}
        </button>
      </header>
      {failed && <p className="board-warn">Cannot reach the server. Showing the last list.</p>}
      <h2>Ready: collect now</h2>
      <ul className="board-ready" aria-label="Ready tokens">
        {(board?.ready ?? []).map((r) => (
          <li key={r.token}>
            <strong>{r.token}</strong>
            <small>{r.outlet}</small>
          </li>
        ))}
        {board && board.ready.length === 0 && <li className="board-none">No order is ready yet</li>}
      </ul>
      <h2>Being made</h2>
      <ul className="board-making" aria-label="Tokens being made">
        {(board?.making ?? []).map((r) => (
          <li key={r.token}>{r.token}</li>
        ))}
      </ul>
    </main>
  );
}
