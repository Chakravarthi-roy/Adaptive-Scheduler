const CACHE = 'scheduler-v1'
const SHELL = ['/', '/index.html', '/app.js', '/style.css', '/icons/icon-192.png', '/icons/icon-512.png']

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(SHELL))
  )
  self.skipWaiting()
})

self.addEventListener('activate', e => {
  // clean old caches
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', e => {
  // network first for API calls, cache first for shell
  if (e.request.url.includes('/api') || e.request.url.includes('onrender.com')) {
    return  // let API calls go through normally
  }
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  )
})

self.addEventListener('push', e => {
  if (!e.data) return

  let title = 'Reminder'
  let body = ''
  let persistent = false
  let action = null
  let action_label = null
  let reminder_id = null
  let sound = true
  let is_pre_alert = false

  try {
    const data = e.data.json()
    title = data.title
    body = data.body
    persistent = data.persistent || false
    action = data.action || null
    action_label = data.action_label || null
    reminder_id = data.reminder_id || null
    sound = data.sound !== false
    is_pre_alert = data.is_pre_alert || false
  } catch {
    title = '🔔 Reminder'
    body = e.data.text()
  }

  const actions = []

  if (is_pre_alert) {
    // Pre-alert: just one OK button — Chrome adds Unsubscribe automatically, keep it simple
    actions.push({ action: 'dismiss_pre', title: 'OK 👍' })
  } else {
    // On-time: just the done action — no snooze button, keeps it uncluttered on mobile
    // User can snooze by tapping the notification body (opens app) if needed
    if (action && action_label) {
      actions.push({ action, title: action_label })
    }
  }

  const options = {
    body,
    vibrate: sound ? [200, 100, 200] : [],
    tag: reminder_id ? `${reminder_id}-${is_pre_alert ? 'pre' : 'main'}` : 'reminder',
    requireInteraction: persistent,
    actions,
    data: {
      url: self.location.origin,
      reminder_id,
      is_pre_alert
    }
  }

  if (sound) options.sound = 'default'

  e.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', e => {
  const action = e.action  // '' = body tapped, 'snooze' / 'dismiss_pre' / custom = button tapped
  const reminder_id = e.notification.data?.reminder_id
  const is_pre_alert = e.notification.data?.is_pre_alert || false
  e.notification.close()

  const API_BASE = 'https://adaptive-scheduler-x6nw.onrender.com'
  // const API_BASE = 'http://localhost:8000'

  // Body tapped (no action button) — just open the app
  if (!action) {
    e.waitUntil(clients.openWindow(e.notification.data.url))
    return
  }

  // Snooze button
  if (action === 'snooze') {
    if (reminder_id) {
      e.waitUntil(
        fetch(`${API_BASE}/reminders/${reminder_id}/snooze`, { method: 'POST' })
          .catch(err => console.log('snooze failed:', err))
      )
    }
    return
  }

  // Pre-alert OK dismiss — just close, nothing else
  if (action === 'dismiss_pre' || is_pre_alert) {
    return
  }

  // Any other action button = mark done (took_it, started, doing, done, etc.)
  if (reminder_id) {
    e.waitUntil(
      fetch(`${API_BASE}/reminders/${reminder_id}/done`, { method: 'PATCH' })
        .catch(err => console.log('mark done failed:', err))
    )
  }
})