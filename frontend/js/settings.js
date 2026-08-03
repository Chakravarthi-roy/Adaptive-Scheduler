import { API_BASE } from './config.js'
import { getNickname, getEmail, isDemo, logout, getAuthHeaders, handle401 } from './auth.js'

// ─── Settings ─────────────────────────────────────────────────────────────────
const SETTINGS_KEY = 'scheduler_settings'

const DEFAULTS = {
  morning:     '08:00',
  evening:     '18:00',
  night:       '21:00',
  inABit:      10,
  afterAWhile: 30,
  vibration:   true,
  timezone:    'Asia/Kolkata'
}

export function loadSettings() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') } }
  catch { return { ...DEFAULTS } }
}

function _writeLocal(s) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s))
}

// Immediate, no-dirty-tracking save — used only by vibration. Its own toggle
// already pushes to the backend the instant it's tapped (see toggleVibration
// below); a Save/Cancel step doesn't make sense for a single on/off switch.
export function saveSettings() {
  const s = {
    ...loadSettings(),
    vibration: document.getElementById('vibration-toggle')?.classList.contains('on') ?? DEFAULTS.vibration
  }
  _writeLocal(s)
}

// ─── Dirty-state tracking — Time Words, Vague Durations, Timezone ─────────
// These three groups used to auto-save on every change (`onchange="saveSettings()"`
// / stepValue calling saveSettings() directly). Now a change only stages a
// pending value; nothing commits (to localStorage OR the backend) until Save
// is tapped, and Cancel reverts every field back to the last committed
// snapshot. Vibration is deliberately excluded from this group — see above.
let _snapshot = null   // last-committed values for the tracked fields, or null before first populate

function _trackedFields() {
  return {
    morning:     document.getElementById('s-morning')?.value ?? DEFAULTS.morning,
    evening:     document.getElementById('s-evening')?.value ?? DEFAULTS.evening,
    night:       document.getElementById('s-night')?.value ?? DEFAULTS.night,
    inABit:      parseInt(document.getElementById('s-in-a-bit')?.value)      || DEFAULTS.inABit,
    afterAWhile: parseInt(document.getElementById('s-after-a-while')?.value) || DEFAULTS.afterAWhile,
    timezone:    document.getElementById('s-timezone')?.value ?? DEFAULTS.timezone
  }
}

function _isDirty() {
  if (!_snapshot) return false
  const current = _trackedFields()
  return Object.keys(current).some(k => String(current[k]) !== String(_snapshot[k]))
}

function _showSaveBar(show) {
  const bar = document.getElementById('settings-savebar')
  if (bar) bar.classList.toggle('show', show)
}

// Called on every change to a tracked field — time inputs, the timezone
// select, and the duration steppers (via stepValue below). Only re-evaluates
// dirty state and shows/hides the bar; never persists anything by itself.
export function onSettingsFieldChange() {
  _showSaveBar(_isDirty())
}

// Save button — commits the staged values to localStorage AND the backend.
// The committed values become the new snapshot Cancel would revert to.
export async function commitSettings() {
  const current = _trackedFields()
  const s = { ...loadSettings(), ...current }
  _writeLocal(s)
  _snapshot = current
  _showSaveBar(false)

  try {
    const res = await fetch(`${API_BASE}/me/settings`, {
      method: 'PATCH',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        timezone:      current.timezone,
        morning:       current.morning,
        evening:       current.evening,
        night:         current.night,
        in_a_bit:      current.inABit,
        after_a_while: current.afterAWhile
      })
    })
    if (res.status === 401) { handle401(); return }
  } catch (err) {
    console.error('could not save settings to backend:', err)
  }
}

// Cancel button — reverts the visible inputs back to the last committed
// snapshot, discarding whatever's currently staged (and un-persisted).
export function cancelSettingsChanges() {
  if (!_snapshot) return
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val }
  set('s-morning',       _snapshot.morning)
  set('s-evening',       _snapshot.evening)
  set('s-night',         _snapshot.night)
  set('s-in-a-bit',      _snapshot.inABit)
  set('s-after-a-while', _snapshot.afterAWhile)
  set('s-timezone',      _snapshot.timezone)
  const d1 = document.getElementById('s-in-a-bit-display')
  const d2 = document.getElementById('s-after-a-while-display')
  if (d1) d1.textContent = _snapshot.inABit
  if (d2) d2.textContent = _snapshot.afterAWhile
  _showSaveBar(false)
}

export function populateSettings() {
  const s = loadSettings()
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val }
  set('s-morning',       s.morning)
  set('s-evening',       s.evening)
  set('s-night',         s.night)
  set('s-in-a-bit',      s.inABit)
  set('s-after-a-while', s.afterAWhile)
  set('s-timezone',      s.timezone)
  const d1 = document.getElementById('s-in-a-bit-display')
  const d2 = document.getElementById('s-after-a-while-display')
  if (d1) d1.textContent = s.inABit
  if (d2) d2.textContent = s.afterAWhile
  const vt = document.getElementById('vibration-toggle')
  if (vt) { s.vibration ? vt.classList.add('on') : vt.classList.remove('on') }

  // Snapshot BEFORE the backend sync below — if the sync corrects a stale
  // local value, it updates the snapshot itself (see _syncSettingsFromBackend),
  // so a drift-correction never gets mistaken for a pending user edit and
  // pops the Save/Cancel bar open on load.
  _snapshot = _trackedFields()
  _showSaveBar(false)

  // The panel only ever reads localStorage above for instant, no-flicker
  // display — but the backend is the actual source of truth (it's what
  // context.py's get_user_tz() and scheduler.py check when reasoning about
  // "current time" and notification timing). Sync from there now, correcting
  // the UI/localStorage/snapshot if they've drifted (e.g. changed on another
  // device, or never synced before this feature existed).
  _syncSettingsFromBackend()

  // Inject Account section once
  if (!document.getElementById('account-section')) {
    const panel   = document.getElementById('settings-panel')
    const section = document.createElement('div')
    section.id        = 'account-section'
    section.className = 'settings-group'
    section.innerHTML = `
      <div class="settings-label">Account</div>
      <div class="settings-item">
        <div class="settings-item-label">
          <span>${getNickname()}</span>
          ${getEmail() ? `<span class="settings-hint">${getEmail()}</span>` : ''}
        </div>
        ${isDemo() ? `<span class="tag tag-casual">demo</span>` : ''}
      </div>
      ${isDemo() ? `
        <div class="settings-item" style="gap:12px">
          <span style="font-size:12px;color:var(--muted);line-height:1.4">Create a free account to keep your reminders</span>
          <a href="/login.html" style="padding:7px 14px;border-radius:9px;background:var(--brown);color:var(--cream);font-size:12px;font-family:'DM Sans',sans-serif;font-weight:600;text-decoration:none;white-space:nowrap;flex-shrink:0">Sign up</a>
        </div>` : ``}
    `
    panel.insertBefore(section, panel.firstChild)
  }

  // Fixed, bottom-center Sign out button — only for real (non-demo) accounts,
  // and only visible while Settings is the active view (it's a child of
  // settings-panel, so it inherits that panel's show/hide from switchView()).
  if (!isDemo() && !document.getElementById('signout-fixed-btn')) {
    const btn = document.createElement('button')
    btn.id        = 'signout-fixed-btn'
    btn.className = 'signout-fixed-btn'
    btn.textContent = 'Sign out'
    btn.onclick = logout
    document.getElementById('settings-panel').appendChild(btn)
  }
}

export function stepValue(id, delta) {
  const input   = document.getElementById(id)
  const display = document.getElementById(id + '-display')
  if (!input || !display) return
  const min = 1, max = 120
  let val = parseInt(input.value) + delta
  val = Math.max(min, Math.min(max, val))
  input.value         = val
  display.textContent = val
  onSettingsFieldChange()
  if (loadSettings().vibration && navigator.vibrate) navigator.vibrate(30)
}

export function toggleVibration() {
  const t = document.getElementById('vibration-toggle')
  t.classList.toggle('on')
  const isOn = t.classList.contains('on')
  if (isOn && navigator.vibrate) navigator.vibrate([80, 40, 80])
  saveSettings()
  _pushVibrationToBackend(isOn)
}

// ─── Vibration backend sync ─────────────────────────────────────────────────
// The toggle used to only ever write to localStorage — meaning the backend
// (and therefore real push notifications, which scheduler.py builds using
// the DB value) never actually knew about it. This is what closes that loop.
async function _pushVibrationToBackend(enabled) {
  try {
    const res = await fetch(`${API_BASE}/me/settings`, {
      method: 'PATCH',
      headers: getAuthHeaders(),
      body: JSON.stringify({ vibration_enabled: enabled })
    })
    if (res.status === 401) { handle401(); return }
  } catch (err) {
    console.error('could not save vibration setting:', err)
  }
}

// ─── Full settings backend sync ─────────────────────────────────────────────
// Pulls vibration + timezone + time-words + vague-durations from the User
// row and corrects localStorage/the DOM/the dirty-tracking snapshot if
// they've drifted from what's actually saved server-side (or never synced
// before this feature existed, in which case the server returns its own
// defaults and this just confirms local matches — a no-op in that case).
async function _syncSettingsFromBackend() {
  try {
    const res = await fetch(`${API_BASE}/me`, { headers: getAuthHeaders() })
    if (res.status === 401) { handle401(); return }
    const data = await res.json()

    const local = loadSettings()
    const merged = {
      ...local,
      vibration:   typeof data.vibration_enabled === 'boolean' ? data.vibration_enabled : local.vibration,
      timezone:    data.timezone      ?? local.timezone,
      morning:     data.morning       ?? local.morning,
      evening:     data.evening       ?? local.evening,
      night:       data.night         ?? local.night,
      inABit:      data.in_a_bit      ?? local.inABit,
      afterAWhile: data.after_a_while ?? local.afterAWhile
    }

    if (JSON.stringify(merged) === JSON.stringify(local)) return   // already in sync

    _writeLocal(merged)

    const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val }
    set('s-morning',       merged.morning)
    set('s-evening',       merged.evening)
    set('s-night',         merged.night)
    set('s-in-a-bit',      merged.inABit)
    set('s-after-a-while', merged.afterAWhile)
    set('s-timezone',      merged.timezone)
    const d1 = document.getElementById('s-in-a-bit-display')
    const d2 = document.getElementById('s-after-a-while-display')
    if (d1) d1.textContent = merged.inABit
    if (d2) d2.textContent = merged.afterAWhile
    const vt = document.getElementById('vibration-toggle')
    if (vt) { merged.vibration ? vt.classList.add('on') : vt.classList.remove('on') }

    // This correction IS the new baseline — not a pending user edit — so
    // fold it into the snapshot rather than leaving the Save/Cancel bar
    // showing for a change the user never actually made.
    _snapshot = _trackedFields()
    _showSaveBar(false)
  } catch (err) {
    console.error('could not sync settings:', err)
  }
}

// ─── Clock ────────────────────────────────────────────────────────────────────
export function updateClock() {
  const s   = loadSettings()
  const tz  = s.timezone || 'Asia/Kolkata'
  const now = new Date()
  const timeEl = document.getElementById('today-time')
  const tzEl   = document.getElementById('tz-badge')
  if (timeEl) timeEl.textContent = now.toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true, timeZone: tz
  })
  if (tzEl) {
    const shortTz = now.toLocaleTimeString('en-US', { timeZoneName: 'short', timeZone: tz })
      .split(' ').pop()
    tzEl.textContent = shortTz
  }
}

export function buildSettingsContext() {
  const s   = loadSettings()
  const tz  = s.timezone || 'Asia/Kolkata'
  const now = new Date()
  const currentDateTime = now.toLocaleString('en-US', {
    timeZone: tz, weekday: 'long', year: 'numeric', month: 'long',
    day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true
  })
  return `[Current time: ${currentDateTime} | User preferences: timezone=${tz}, "morning"=${s.morning}, "evening"=${s.evening}, "night"=${s.night}, "in a bit"=${s.inABit} minutes, "after a while"=${s.afterAWhile} minutes]`
}