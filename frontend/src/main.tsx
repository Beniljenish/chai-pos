import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fontsource/plus-jakarta-sans/800.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AdminApp } from './app/AdminApp';
import { App } from './app/App';
import { CustomerApp } from './app/CustomerApp';
import { courtSlugFromPath } from './lib/foodcourt';
import { SessionProvider } from './app/session';
import './styles.css';

// A food court's QR opens /order/<court>: the customer's page, with no login and none
// of the staff app. Everything else is the staff app.
const court = courtSlugFromPath(window.location.pathname);
// The super admin's page. It is only a page: signing in is what decides who may do anything.
const admin = /^\/admin\/?$/.test(window.location.pathname);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {admin ? (
      <AdminApp />
    ) : court ? (
      <CustomerApp slug={court} />
    ) : (
      <SessionProvider>
        <App />
      </SessionProvider>
    )}
  </StrictMode>,
);
