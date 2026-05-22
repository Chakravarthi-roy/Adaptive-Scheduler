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

  try {
    const data = e.data.json()
    title = data.title
    body = data.body
    persistent = data.persistent || false
    action = data.action || null
    action_label = data.action_label || null
    reminder_id = data.reminder_id || null
  } catch {
    title = '🔔 Reminder'
    body = e.data.text()
  }

  // build actions array for notification buttons
  const actions = []
  if (action && action_label) {
    actions.push({ action, title: action_label })
  }
  actions.push({ action: 'snooze', title: 'Snooze 10m ⏰' })

  const options = {
    body,
    vibrate: [200, 100, 200],
    tag: reminder_id || 'reminder',
    requireInteraction: persistent,
    actions,
    data: {
      url: self.location.origin,
      reminder_id
    }
  }

  e.waitUntil(
    self.registration.showNotification(title, options)
  )
})

self.addEventListener('notificationclick', e => {
  const action = e.action
  const reminder_id = e.notification.data?.reminder_id
  e.notification.close()

  if (action === 'snooze' && reminder_id) {
    // tell backend to snooze this reminder by 10 mins
    e.waitUntil(
      fetch(`${self.location.origin.replace('frontend', 'api')}/reminders/${reminder_id}/snooze`, {
        method: 'POST'
      }).catch(err => console.log('snooze failed:', err))
    )
    return
  }

  if (action === 'taken' || action === 'on_it' || action === 'done' || action === 'on_way') {
    // mark reminder as done when user taps action button
    if (reminder_id) {
      e.waitUntil(
        fetch(`${self.location.origin.replace('frontend', 'api')}/reminders/${reminder_id}/done`, {
          method: 'PATCH'
        }).catch(err => console.log('mark done failed:', err))
      )
    }
    return
  }

  // default — open the app
  e.waitUntil(
    clients.openWindow(e.notification.data.url)
  )
})