/* Phone notifications (Web Push). Pulled into the app's service worker by the build
 * (vite.config.ts, workbox importScripts). Shows what the server sent, and a tap opens the
 * food court page. The message is sent by services/extras.py when an order is ready. */
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'Your order', body: event.data ? event.data.text() : '' };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || 'Your order', {
      body: data.body || '',
      tag: data.tag || 'order',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: data.url || '/order' },
      requireInteraction: true,
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/order';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const w of windows) {
        if (w.url.includes('/order') && 'focus' in w) return w.focus();
      }
      return self.clients.openWindow(url);
    }),
  );
});
