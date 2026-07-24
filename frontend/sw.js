const CACHE = 'scheduler-v3'
const SHELL = [
  '/', '/index.html', '/style.css', '/icons/icon-192.png', '/icons/icon-512.png',
  '/js/main.js', '/js/config.js', '/js/dom.js', '/js/auth.js', '/js/push.js',
  '/js/settings.js', '/js/chat.js', '/js/modal.js', '/js/reminders.js',
  '/js/views.js', '/js/tour.js'
]

// Reads the auth token from IndexedDB (mirrored here from app.js/login.html —
// localStorage isn't accessible from a service worker). Without this, the
// done/snooze fetches below get sent with NO Authorization header, the
// backend silently returns 401, and fetch() doesn't treat a 401 as a
// failure — so the button LOOKS like it worked but nothing ever happened
// server-side. This was the actual cause of reminders showing "missed"
// even after clicking the notification's action button.
function getStoredToken() {
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open('scheduler-auth', 1)
      req.onupgradeneeded = () => { req.result.createObjectStore('auth') }
      req.onsuccess = () => {
        const db = req.result
        try {
          const tx = db.transaction('auth', 'readonly')
          const getReq = tx.objectStore('auth').get('token')
          getReq.onsuccess = () => resolve(getReq.result || null)
          getReq.onerror   = () => resolve(null)
        } catch (e) { resolve(null) }
      }
      req.onerror = () => resolve(null)
    } catch (e) { resolve(null) }
  })
}

function authedFetch(url, options) {
  return getStoredToken().then(token => {
    if (!token) {
      console.log('[sw] no auth token available in IndexedDB — request will fail')
    }
    return fetch(url, {
      ...options,
      headers: { ...(options.headers || {}), ...(token ? { 'Authorization': `Bearer ${token}` } : {}) }
    }).then(res => {
      if (!res.ok) {
        // fetch() does NOT reject on non-2xx status — without this, a 401/404/500
        // here would silently do nothing while looking like it worked, exactly
        // like the original bug this function was written to fix.
        console.log(`[sw] request to ${url} failed with status ${res.status}`)
      }
      return res
    })
  })
}

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
        authedFetch(`${API_BASE}/reminders/${reminder_id}/snooze`, { method: 'POST' })
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
      authedFetch(`${API_BASE}/reminders/${reminder_id}/done`, { method: 'PATCH' })
        .catch(err => console.log('mark done failed:', err))
    )
  }
})