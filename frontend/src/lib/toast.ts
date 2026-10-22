/** A tiny "Saved ✓" notice: any screen calls toast(), the one ToastHost shows it. */
type Listener = (message: string) => void;
const listeners = new Set<Listener>();

export function toast(message: string): void {
  listeners.forEach((l) => l(message));
}

export function onToast(l: Listener): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}
