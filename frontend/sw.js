self.addEventListener('install', e => {
  console.log('service worker installed')
  self.skipWaiting()
})

self.addEventListener('activate', e => {
  console.log('service worker activated')
  self.clients.claim()
})

self.addEventListener('push', e => {
  if (!e.data) return

  let title = 'Reminder'
  let body = ''
  let persistent = false

  try {
    const data = e.data.json()
    title = data.title
    body = data.body
    persistent = data.persistent || false
  } catch {
    title = '🔔 Reminder'
    body = e.data.text()
  }

  const options = {
    body,
    vibrate: [200, 100, 200],
    tag: 'reminder',
    requireInteraction: persistent,
    data: { url: self.location.origin }
  }

  e.waitUntil(
    self.registration.showNotification(title, options)
  )
})

self.addEventListener('notificationclick', e => {
  e.notification.close()
  e.waitUntil(
    clients.openWindow(e.notification.data.url)
  )
})