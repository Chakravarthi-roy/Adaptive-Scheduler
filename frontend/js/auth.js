// NOTE: the actual auth guard lives as a plain inline <script> in index.html,
// BEFORE the module script tag — not here. ES module imports are hoisted and
// fully evaluated before any importing file's own top-level code runs, so a
// guard placed inside a module would run too late to actually guard anything.

// ─── AUTH HELPERS ─────────────────────────────────────────────────────────────
export function getToken()    { return localStorage.getItem('scheduler_token') || '' }
export function getNickname() { return localStorage.getItem('scheduler_nickname') || 'You' }
export function getEmail()    { return localStorage.getItem('scheduler_email') || '' }
export function isDemo()      { return localStorage.getItem('scheduler_is_demo') === 'true' }

export function getAuthHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${getToken()}`
  }
}

// ─── Service-worker-accessible token store ───────────────────────────────────
// localStorage isn't readable from a service worker (different execution
// context) — but a notification-click handler runs IN the service worker, and
// needs the token to make an authenticated fetch (marking done, snoozing).
// IndexedDB is readable from both, so the token gets mirrored here too,
// kept in sync wherever it's set/cleared in localStorage.
export function saveTokenForServiceWorker(token) {
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open('scheduler-auth', 1)
      req.onupgradeneeded = () => { req.result.createObjectStore('auth') }
      req.onsuccess = () => {
        const db = req.result
        const tx = db.transaction('auth', 'readwrite')
        tx.objectStore('auth').put(token, 'token')
        tx.oncomplete = () => resolve()
        tx.onerror    = () => resolve()
      }
      req.onerror = () => resolve()
    } catch (e) { resolve() }
  })
}
export function clearTokenForServiceWorker() { return saveTokenForServiceWorker(null) }

// Sync existing sessions too — people already logged in before this fix
// shipped would otherwise have a token in localStorage but nothing in
// IndexedDB until their next login, leaving notification actions broken
// until then. Harmless to call on every load either way.
export function syncTokenToServiceWorker() {
  if (getToken()) { saveTokenForServiceWorker(getToken()) }
}

export function handle401() {
  localStorage.removeItem('scheduler_token')
  localStorage.removeItem('scheduler_nickname')
  localStorage.removeItem('scheduler_email')
  localStorage.removeItem('scheduler_is_demo')
  clearTokenForServiceWorker()
  window.location.replace('/login.html')
}

export function logout() {
  localStorage.clear()
  clearTokenForServiceWorker()
  window.location.replace('/login.html')
}