import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fontsource/plus-jakarta-sans/800.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ToastHost } from './app/ToastHost';
import { AdminApp } from './app/AdminApp';
import { BoardApp } from './app/BoardApp';
import { App } from './app/App';
import { CustomerApp } from './app/CustomerApp';
import { boardSlugFromPath, courtSlugFromPath, isOrderHome } from './lib/foodcourt';
import { SessionProvider } from './app/session';
import './styles.css';

// A food court's QR opens /order/<court>, and /order is the customer front door: the
// customer's pages (their own account), none of the staff app. Everything else is the staff app.
const court = courtSlugFromPath(window.location.pathname);
const orderHome = isOrderHome(window.location.pathname); // /order: log in, then choose a court
// The super admin's page. It is only a page: signing in is what decides who may do anything.
// /board/<court>: the display for a TV at the food court. No login, tokens only.
const board = boardSlugFromPath(window.location.pathname);
const admin = /^\/admin\/?$/.test(window.location.pathname);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {admin ? (
      <AdminApp />
    ) : board ? (
      <BoardApp slug={board} />
    ) : court || orderHome ? (
      <CustomerApp slug={court} />
    ) : (
      <SessionProvider>
        <App />
      </SessionProvider>
    )}
    <ToastHost />
  </StrictMode>,
);
