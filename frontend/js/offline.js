// ─── Offline indicator ────────────────────────────────────────────────────
// Nothing else in the app currently tells the user they've lost connectivity
// — requests to /reminders, /agent, etc. just fail quietly into a console.log
// or a generic alert. This adds an unmissable banner the moment the browser
// goes offline, and removes it the moment it's back, using the browser's own
// online/offline signal — no polling needed.

let _bannerEl = null

function _showOfflineBanner() {
  if (_bannerEl) return   // already showing
  _bannerEl = document.createElement('div')
  _bannerEl.className = 'offline-banner'
  _bannerEl.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <line x1="1" y1="1" x2="23" y2="23"/>
      <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/>
      <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/>
      <path d="M10.71 5.05A16 16 0 0 1 22.58 9"/>
      <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/>
      <path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
      <line x1="12" y1="20" x2="12.01" y2="20"/>
    </svg>
    <span>You're offline — changes won't save until you're back</span>`
  document.body.appendChild(_bannerEl)
}

function _hideOfflineBanner() {
  if (_bannerEl) { _bannerEl.remove(); _bannerEl = null }
}

export function initOfflineIndicator() {
  if (!navigator.onLine) _showOfflineBanner()   // catches "loaded the page while already offline"
  window.addEventListener('offline', _showOfflineBanner)
  window.addEventListener('online', _hideOfflineBanner)
}