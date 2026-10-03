/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv, type Plugin } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

/**
 * Strict Content Security Policy, added to production builds only (Vite's dev
 * server injects its own scripts). Scripts may come only from this app itself,
 * and the app may talk only to itself and the API. This is what makes keeping
 * the refresh token in IndexedDB an acceptable trade-off: no third-party or
 * injected script can run to read it.
 */
function contentSecurityPolicy(apiUrl: string): Plugin {
  const apiOrigin = new URL(apiUrl, 'http://placeholder.invalid').origin;
  const connect = apiOrigin === 'http://placeholder.invalid' ? "'self'" : `'self' ${apiOrigin}`;
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "font-src 'self'",
    "img-src 'self' data:",
    `connect-src ${connect}`,
    "manifest-src 'self'",
    "worker-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join('; ');
  return {
    name: 'chai-pos-csp',
    apply: 'build',
    transformIndexHtml: (html) =>
      html.replace('<head>', `<head>\n    <meta http-equiv="Content-Security-Policy" content="${csp}" />`),
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiUrl = env.VITE_API_URL || 'http://localhost:8000/api/v1';
  return {
    plugins: [
      react(),
      contentSecurityPolicy(apiUrl),
      VitePWA({
        registerType: 'autoUpdate',
        includeAssets: ['icon-192.png'],
        manifest: {
          name: 'Chai POS',
          short_name: 'Chai POS',
          description: 'Billing and stock for tea and juice shops. Works offline.',
          start_url: '/',
          display: 'standalone',
          orientation: 'any',
          background_color: '#E6EAED',
          theme_color: '#1F6B4F',
          icons: [
            { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
            { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
            { src: 'icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          ],
        },
        workbox: {
          // The whole app shell is cached, so the app opens with no internet at all.
          globPatterns: ['**/*.{js,css,html,woff2,png,svg}'],
          navigateFallback: '/index.html',
          // API calls are never cached by the service worker: offline data lives
          // in IndexedDB, where we control it, not in an HTTP cache.
          navigateFallbackDenylist: [/^\/api\//],
        },
      }),
    ],
    define: {
      __API_URL__: JSON.stringify(apiUrl),
      // Which build a tablet runs (PWAs update in the background): Vercel's commit, or "dev".
      __APP_VERSION__: JSON.stringify((process.env.VERCEL_GIT_COMMIT_SHA ?? 'dev').slice(0, 7)),
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
    },
  };
});
