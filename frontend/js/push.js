import { API_BASE, VAPID_PUBLIC_KEY } from './config.js'
import { getToken, handle401 } from './auth.js'

// ─── PUSH SETUP ───────────────────────────────────────────────────────────────
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4)
  const base64  = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return new Uint8Array([...rawData].map(c => c.charCodeAt(0)))
}

export async function initPush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return
  try {
    const reg        = await navigator.serviceWorker.register('./sw.js')
    await navigator.serviceWorker.ready
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') return
    const subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
    })
    const res = await fetch(`${API_BASE}/subscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getToken()}`
      },
      body: JSON.stringify(subscription)
    })
    if (res.status === 401) handle401()
  } catch (err) {
    console.error('push setup error:', err)
  }
}