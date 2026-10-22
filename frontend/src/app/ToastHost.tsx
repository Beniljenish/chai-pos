import { useEffect, useState } from 'react';
import { onToast } from '../lib/toast';

const SHOW_MS = 2400;

export function ToastHost() {
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const off = onToast((m) => {
      setMessage(m);
      clearTimeout(timer);
      timer = setTimeout(() => setMessage(null), SHOW_MS);
    });
    return () => {
      off();
      clearTimeout(timer);
    };
  }, []);
  return (
    <div className="toast-host" aria-live="polite">
      {message && <div className="toast">✓ {message}</div>}
    </div>
  );
}
