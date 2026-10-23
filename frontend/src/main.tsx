import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fontsource/plus-jakarta-sans/800.css';
import { lazy, StrictMode, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { ToastHost } from './app/ToastHost';
import { CrashScreen } from './app/CrashScreen';
import { installErrorReporting } from './lib/reportError';
import { boardSlugFromPath, courtSlugFromPath, isOrderHome } from './lib/foodcourt';
import './styles.css';

// Each audience downloads only its own app: a customer scanning a table QR does not load the
// till, Manage or the admin page. All chunks are still precached by the service worker, so the
// till opens offline as before.
const StaffRoot = lazy(() => import('./app/StaffRoot').then((m) => ({ default: m.StaffRoot })));
const AdminApp = lazy(() => import('./app/AdminApp').then((m) => ({ default: m.AdminApp })));
const BoardApp = lazy(() => import('./app/BoardApp').then((m) => ({ default: m.BoardApp })));
const CustomerApp = lazy(() => import('./app/CustomerApp').then((m) => ({ default: m.CustomerApp })));

// A food court's QR opens /order/<court>, and /order is the customer front door: the
// customer's pages (their own account), none of the staff app. Everything else is the staff app.
const court = courtSlugFromPath(window.location.pathname);
const orderHome = isOrderHome(window.location.pathname); // /order: log in, then choose a court
// The super admin's page. It is only a page: signing in is what decides who may do anything.
// /board/<court>: the display for a TV at the food court. No login, tokens only.
const board = boardSlugFromPath(window.location.pathname);
const admin = /^\/admin\/?$/.test(window.location.pathname);

installErrorReporting();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <CrashScreen>
    <Suspense fallback={<div className="app-loading" aria-busy="true" />}>
    {admin ? (
      <AdminApp />
    ) : board ? (
      <BoardApp slug={board} />
    ) : court || orderHome ? (
      <CustomerApp slug={court} />
    ) : (
      <StaffRoot />
    )}
    </Suspense>
    </CrashScreen>
    <ToastHost />
  </StrictMode>,
);
