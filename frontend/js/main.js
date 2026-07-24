// ─── main.js — entry point ──────────────────────────────────────────────────
// Loaded as <script type="module"> from index.html. Runs the auth guard
// first (before anything else touches the page), then wires every other
// module together.
//
// ES modules are scoped, not global — but the HTML (both the static markup
// in index.html and dynamically-generated strings in reminders.js/settings.js/
// tour.js) calls a handful of functions via inline onclick="..." attributes,
// which can only resolve against `window`. Those specific functions are
// exposed below; everything else stays properly module-scoped.

import { isDemo, syncTokenToServiceWorker, logout } from './auth.js'

// Auth guard already ran (see the inline script in index.html, BEFORE this
// module tag) — by the time this file's own code runs, we're guaranteed to
// have a token. Just sync it to IndexedDB for the service worker's benefit.
syncTokenToServiceWorker()

import { switchView } from './views.js'
import { saveSettings, stepValue, toggleVibration, updateClock } from './settings.js'
import { markDone, loadReminders } from './reminders.js'
import { setupDemoMode, endTour, _nextTourStep, _pauseForAction, _waitForSave } from './tour.js'
import { initPush } from './push.js'
import './chat.js'   // attaches its own event listeners (mic/type/close-chat) on import
import './modal.js'  // attaches its own event listeners (save/cancel) on import

// ─── Bridge for inline onclick="..." handlers in HTML ──────────────────────
window.switchView       = switchView
window.saveSettings     = saveSettings
window.stepValue        = stepValue
window.toggleVibration  = toggleVibration
window.markDone         = markDone
window.logout           = logout
window.endTour          = endTour
window._nextTourStep    = _nextTourStep
window._pauseForAction  = _pauseForAction
window._waitForSave     = _waitForSave

// ─── Date ─────────────────────────────────────────────────────────────────────
document.getElementById('today-date').textContent = new Date().toLocaleDateString('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
})

// ─── Clock ────────────────────────────────────────────────────────────────────
updateClock()
setInterval(updateClock, 1000)

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Always inject demo visitor card style — needed for admin to see demo reminders in amber
  const visitorStyle = document.createElement('style')
  visitorStyle.textContent = `
    .card.demo-visitor-card {
      background: rgba(221,161,94,0.07);
      border: 1.5px dashed rgba(221,161,94,0.45);
    }
  `
  document.head.appendChild(visitorStyle)
  // Demo banner at top of reminders area
  if (isDemo()) {
    const banner = document.createElement('div')
    banner.id = 'demo-banner'
    banner.style.cssText = 'background:rgba(181,131,90,0.1);border:1px solid rgba(181,131,90,0.22);border-radius:10px;padding:10px 14px;margin-bottom:4px;font-size:12px;color:var(--muted);display:flex;align-items:center;gap:8px;line-height:1.4'
    banner.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;color:var(--brown)"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      <span>Demo mode — <a href="/login.html" style="color:var(--brown);font-weight:600;text-decoration:none">create a free account</a> to keep your reminders.</span>`
    document.getElementById('reminders-area').before(banner)
  }

  setupDemoMode()
  loadReminders()
  initPush()
})