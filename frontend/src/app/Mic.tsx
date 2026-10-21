/** A microphone button: tap, speak, and the words appear. Hidden where the browser cannot listen. */
import { useEffect, useRef, useState } from 'react';
import { getLang, t } from '../lib/i18n';
import { canListen, listen } from '../lib/voice';

export function Mic({ onText, label }: { onText(text: string, final: boolean): void; label?: string }) {
  const [on, setOn] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);
  if (!canListen()) return null;

  function toggle() {
    if (on) {
      stop.current?.();
      return;
    }
    setProblem(null);
    setOn(true);
    stop.current = listen(getLang(), {
      onText,
      onEnd: () => setOn(false),
      onError: (kind) =>
        setProblem(
          kind === 'denied'
            ? t('The microphone is blocked. Allow it for this site in the browser settings.')
            : kind === 'none'
              ? t('Nothing was heard. Tap and try again.')
              : t('Listening did not work here. Type it instead.'),
        ),
    });
  }

  return (
    <div className="mic">
      <button type="button" className={`mic-btn ${on ? 'on' : ''}`} aria-pressed={on} onClick={toggle}>
        <span aria-hidden="true">{on ? '■' : '🎤'}</span>
        <span>{on ? t('Listening… tap to stop') : (label ?? t('Tap and speak'))}</span>
      </button>
      {problem && (
        <p className="error" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}
