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
    // Pre-alert: just an "OK" dismiss — no mark-done
    actions.push({ action: 'dismiss_pre', title: 'OK 👍' })
    actions.push({ action: 'snooze', title: 'Snooze 10m ⏰' })
  } else {
    // On-time: show the real action (mark done / took it / etc.)
    if (action && action_label) {
      actions.push({ action, title: action_label })
    }
    actions.push({ action: 'snooze', title: 'Snooze 10m ⏰' })
  }

  const options = {
    body,
    vibrate: [200, 100, 200],
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
  const action = e.action
  const reminder_id = e.notification.data?.reminder_id
  const is_pre_alert = e.notification.data?.is_pre_alert || false
  e.notification.close()

  const API_BASE = 'https://adaptive-scheduler-x6nw.onrender.com'

  // Snooze — works for both pre-alert and on-time
  if (action === 'snooze' && reminder_id) {
    e.waitUntil(
      fetch(`${API_BASE}/reminders/${reminder_id}/snooze`, { method: 'POST' })
        .catch(err => console.log('snooze failed:', err))
    )
    return
  }

  // Pre-alert dismiss — just close, do nothing
  if (action === 'dismiss_pre' || is_pre_alert) {
    return
  }

  // On-time action (mark done / took it / etc.)
  if (action && action !== 'snooze' && reminder_id) {
    e.waitUntil(
      fetch(`${API_BASE}/reminders/${reminder_id}/done`, { method: 'PATCH' })
        .catch(err => console.log('mark done failed:', err))
    )
    return
  }

  // Default — open the app
  e.waitUntil(clients.openWindow(e.notification.data.url))
})