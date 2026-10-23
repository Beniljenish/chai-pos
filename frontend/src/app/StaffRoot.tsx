import { App } from './App';
import { SessionProvider } from './session';

/** The staff app with its session (offline bills, sync): one chunk only staff devices load. */
export function StaffRoot() {
  return (
    <SessionProvider>
      <App />
    </SessionProvider>
  );
}
