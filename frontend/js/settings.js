import { getNickname, getEmail, isDemo, logout } from './auth.js'

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

export function saveSettings() {
  const s = {
    morning:     document.getElementById('s-morning')?.value      || DEFAULTS.morning,
    evening:     document.getElementById('s-evening')?.value      || DEFAULTS.evening,
    night:       document.getElementById('s-night')?.value        || DEFAULTS.night,
    inABit:      parseInt(document.getElementById('s-in-a-bit')?.value)      || DEFAULTS.inABit,
    afterAWhile: parseInt(document.getElementById('s-after-a-while')?.value) || DEFAULTS.afterAWhile,
    vibration:   document.getElementById('vibration-toggle')?.classList.contains('on') ?? DEFAULTS.vibration,
    timezone:    document.getElementById('s-timezone')?.value || DEFAULTS.timezone
  }
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s))
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
        </div>` : `
        <div class="settings-item">
          <span>Sign out</span>
          <button onclick="logout()" style="padding:6px 16px;border-radius:8px;background:var(--mint);border:1.5px solid var(--border);color:var(--muted);font-size:12px;font-family:'DM Sans',sans-serif;cursor:pointer;transition:background 0.15s" onmouseover="this.style.background='var(--sage)'" onmouseout="this.style.background='var(--mint)'">Sign out</button>
        </div>`}
    `
    panel.insertBefore(section, panel.firstChild)
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
  saveSettings()
  if (loadSettings().vibration && navigator.vibrate) navigator.vibrate(30)
}

export function toggleVibration() {
  const t = document.getElementById('vibration-toggle')
  t.classList.toggle('on')
  const isOn = t.classList.contains('on')
  if (isOn && navigator.vibrate) navigator.vibrate([80, 40, 80])
  saveSettings()
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