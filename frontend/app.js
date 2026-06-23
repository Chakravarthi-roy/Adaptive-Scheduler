// ─── AUTH GUARD — runs before anything else ────────────────────────────────────
// If there's no token, kick to login immediately
;(function () {
  if (!localStorage.getItem('scheduler_token')) {
    window.location.replace('/login.html')
  }
})()

// ─── CONFIG ───────────────────────────────────────────────────────────────────
const API_BASE = 'https://adaptive-scheduler-x6nw.onrender.com'
// const API_BASE = 'http://localhost:8000'

const VAPID_PUBLIC_KEY = 'BLdUTJ82_k03z93xAJadQ2U58tp-V5ICr_g4Hf_20L6uJ0C9XDnLHxgux-UOJ-QjLMFzoTaP4oTwx5FktGWeSyY'

// ─── AUTH HELPERS ──────────────────────────────────────────────────────────────
function getToken()    { return localStorage.getItem('scheduler_token') || '' }
function getNickname() { return localStorage.getItem('scheduler_nickname') || 'You' }
function getEmail()    { return localStorage.getItem('scheduler_email') || '' }
function isDemo()      { return localStorage.getItem('scheduler_is_demo') === 'true' }

// JSON request headers + auth token
function getAuthHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${getToken()}`
  }
}

// Called whenever the server says 401 — clear local state and send to login
function handle401() {
  localStorage.removeItem('scheduler_token')
  localStorage.removeItem('scheduler_nickname')
  localStorage.removeItem('scheduler_email')
  localStorage.removeItem('scheduler_is_demo')
  window.location.replace('/login.html')
}

function logout() {
  localStorage.clear()
  window.location.replace('/login.html')
}

// ─── PUSH SETUP ───────────────────────────────────────────────────────────────
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return new Uint8Array([...rawData].map(c => c.charCodeAt(0)))
}

async function initPush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return
  try {
    const reg = await navigator.serviceWorker.register('./sw.js')
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

// ─── Date & Live Clock ───────────────────────────────────────────────────────
document.getElementById('today-date').textContent = new Date().toLocaleDateString('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
})

// clock started after settings loaded — see bottom of Settings section

// ─── State ────────────────────────────────────────────────────────────────────
let mediaRecorder = null
let audioChunks = []
let recording = false
let agentMessages = []
let awaitingReply = false
let currentView = 'reminders'

// ─── Elements ─────────────────────────────────────────────────────────────────
const micBtn      = document.getElementById('mic-btn')
const typeBtn     = document.getElementById('type-btn')
const typeArea    = document.getElementById('type-area')
const typeInput   = document.getElementById('type-input')
const typeSend    = document.getElementById('type-send')
const chatBubbles = document.getElementById('chat-bubbles')
const overlay     = document.getElementById('overlay')
const btnCancel   = document.getElementById('btn-cancel')
const btnCancel2  = document.getElementById('btn-cancel-2')
const btnSave     = document.getElementById('btn-save')
const micToast    = document.getElementById('mic-toast')

// ─── Toast ────────────────────────────────────────────────────────────────────
let toastTimer = null
function showToast(msg) {
  micToast.textContent = msg
  micToast.classList.add('show')
  clearTimeout(toastTimer)
  if (msg) toastTimer = setTimeout(() => micToast.classList.remove('show'), 3000)
}

// ─── Mic State ────────────────────────────────────────────────────────────────
function setMicState(state) {
  micBtn.classList.remove('recording', 'processing')
  typeBtn.style.display = awaitingReply ? 'flex' : 'none'
  switch (state) {
    case 'recording':
      micBtn.classList.add('recording')
      break
    case 'processing':
    case 'thinking':
      micBtn.classList.add('processing')
      break
  }
}

// ─── Chat Bubbles ─────────────────────────────────────────────────────────────
function addBubble(text, role) {
  const wrap = document.createElement('div')
  wrap.className = `bubble-wrap ${role}`
  const bubble = document.createElement('div')
  bubble.className = `bubble bubble-${role}`
  bubble.textContent = text
  wrap.appendChild(bubble)
  chatBubbles.appendChild(wrap)
  chatBubbles.scrollTop = chatBubbles.scrollHeight
}

function clearBubbles() { chatBubbles.innerHTML = '' }

// ─── Recording ────────────────────────────────────────────────────────────────
micBtn.addEventListener('click', async () => {
  if (!recording) await startRecording()
  else stopRecording()
})

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder = new MediaRecorder(stream)
    audioChunks = []
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data) }
    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' })
      await handleAudioInput(audioBlob)
      stream.getTracks().forEach(t => t.stop())
    }
    mediaRecorder.start()
    recording = true
    setMicState('recording')
  } catch (err) {
    alert('Microphone access denied.')
    console.error(err)
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop()
  recording = false
  setMicState('processing')
}

// ─── Type Button ──────────────────────────────────────────────────────────────
typeBtn.addEventListener('click', () => {
  typeArea.classList.toggle('show')
  if (typeArea.classList.contains('show')) typeInput.focus()
})

typeSend.addEventListener('click', () => sendTypedReply())
typeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendTypedReply() })

function sendTypedReply() {
  const text = typeInput.value.trim()
  if (!text) return
  typeInput.value = ''
  typeArea.classList.remove('show')
  handleTextInput(text)
}

// ─── Input Handlers ───────────────────────────────────────────────────────────
async function handleAudioInput(audioBlob) {
  if (audioBlob.size < 1000) {
    setMicState('idle')
    alert('Recording too short — please speak for at least 2 seconds.')
    return
  }
  setMicState('processing')
  try {
    const formData = new FormData()
    formData.append('audio', audioBlob, 'recording.webm')
    // Note: don't set Content-Type for FormData — browser sets it with boundary
    const res = await fetch(`${API_BASE}/transcribe`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` },
      body: formData
    })
    if (res.status === 401) { handle401(); return }
    const data = await res.json()
    const transcript = data.transcript?.trim()
    if (!transcript) {
      setMicState('idle')
      alert('Could not hear anything. Try speaking louder.')
      return
    }
    await handleTextInput(transcript)
  } catch (err) {
    console.error(err)
    setMicState('idle')
    alert('Something went wrong during transcription.')
  }
}

async function handleTextInput(text) {
  // cancel detection — reset everything if user says cancel/stop/nevermind
  const cancelWords = ['cancel', 'stop', 'never mind', 'nevermind', 'forget it', 'nope', 'abort']
  if (cancelWords.some(w => text.toLowerCase().includes(w)) && agentMessages.length > 0) {
    resetConversation()
    setMicState('idle')
    return
  }

  addBubble(text, 'user')
  // prepend settings context to first user message so agent knows time preferences
  const msgContent = agentMessages.length === 0
    ? buildSettingsContext() + '\n' + text
    : text
  agentMessages.push({ role: 'user', content: msgContent })
  setMicState('thinking')
  awaitingReply = false

  try {
    const res = await fetch(`${API_BASE}/agent`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ messages: agentMessages })
    })
    if (res.status === 401) { handle401(); return }
    const result = await res.json()

    if (result.messages) {
      agentMessages = result.messages.filter(m => m.role !== 'system')
    }

    if (result.type === 'question') {
      awaitingReply = true
      addBubble(result.text, 'agent')
      setMicState('idle')

    } else if (result.type === 'reminder') {
      awaitingReply = false
      setMicState('idle')
      showConfirmModal(result.data)

    } else if (result.type === 'updated') {
      awaitingReply = false
      addBubble(result.text, 'agent')
      setMicState('idle')
      loadReminders()
      setTimeout(resetConversation, 1800)

    } else if (result.type === 'deleted') {
      awaitingReply = false
      addBubble(result.text, 'agent')
      setMicState('idle')
      loadReminders()
      setTimeout(resetConversation, 1800)

    } else if (result.type === 'error') {
      awaitingReply = false
      addBubble(result.text, 'agent')
      setMicState('idle')
    }

  } catch (err) {
    console.error(err)
    awaitingReply = false
    setMicState('idle')
    alert('Something went wrong — check the console.')
  }
}

// ─── Confirm Modal ────────────────────────────────────────────────────────────
let _pendingExtracted = null

const SAVE_BTN_LABEL = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Save Reminder`

function showConfirmModal(extracted) {
  _pendingExtracted = extracted  // keep full agent data — action_label, pre_alert_minutes, etc.
  document.getElementById('field-title').value    = extracted.title    || ''
  document.getElementById('field-location').value = extracted.location || ''
  document.getElementById('field-type').value     = extracted.type     || 'personal'
  document.getElementById('field-repeat').value   = extracted.repeat   || 'none'
  document.getElementById('field-datetime').value = extracted.datetime
    ? extracted.datetime.slice(0, 16) : ''
  document.getElementById('field-pre-alert').value = extracted.pre_alert_minutes ?? ''
  document.getElementById('field-follow-up').value = extracted.follow_up_minutes ?? ''
  overlay.classList.add('show')
}

function closeModal() {
  overlay.classList.remove('show')
  resetConversation()
}

btnCancel.addEventListener('click', closeModal)
btnCancel2.addEventListener('click', closeModal)

btnSave.addEventListener('click', async () => {
  const title = document.getElementById('field-title').value
  if (!title.trim()) { alert('Title cannot be empty.'); return }

  btnSave.disabled = true
  btnSave.textContent = 'Saving…'

  const reminder = {
    title,
    datetime:          document.getElementById('field-datetime').value || null,
    location:          document.getElementById('field-location').value || null,
    type:              document.getElementById('field-type').value,
    repeat:            document.getElementById('field-repeat').value,
    participants:      _pendingExtracted?.participants || [],
    action_label:      _pendingExtracted?.action_label || null,
    pre_alert_minutes: document.getElementById('field-pre-alert').value !== ''
                         ? parseInt(document.getElementById('field-pre-alert').value) : null,
    follow_up_minutes: document.getElementById('field-follow-up').value !== ''
                         ? parseInt(document.getElementById('field-follow-up').value) : null
  }

  try {
    const res = await fetch(`${API_BASE}/reminders`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(reminder)
    })
    if (res.status === 401) { handle401(); return }
    const data = await res.json()
    if (data.status === 'saved') {
      overlay.classList.remove('show')
      resetConversation()
      loadReminders()
    }
  } catch (err) {
    alert('Could not save. Is the backend running?')
  } finally {
    btnSave.disabled = false
    btnSave.innerHTML = SAVE_BTN_LABEL
  }
})

function resetConversation() {
  agentMessages = []
  awaitingReply = false
  clearBubbles()
  setMicState('idle')
}

// ─── Reminders ────────────────────────────────────────────────────────────────
let _allReminders = []

function showSkeleton() {
  document.getElementById('reminder-count').textContent = ''
  const area = document.getElementById('reminders-area')
  area.innerHTML = Array.from({length: 3}, () => `
    <div class="card skeleton-card">
      <div class="sk sk-dot"></div>
      <div class="sk-body">
        <div class="sk sk-title"></div>
        <div class="sk sk-sub"></div>
      </div>
      <div class="sk sk-tag"></div>
    </div>`).join('')
}

async function loadReminders() {
  if (currentView === 'settings') return
  showSkeleton()
  try {
    const res = await fetch(`${API_BASE}/reminders`, {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    })
    if (res.status === 401) { handle401(); return }
    _allReminders = await res.json()
    renderReminders(_allReminders)
  } catch (err) {
    console.error('could not load reminders:', err)
    const area = document.getElementById('reminders-area')
    area.innerHTML = `<div class="empty-state"><div class="empty-icon">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
      </svg></div>
      <p>Couldn't load reminders</p>
      <span>Check your connection and try again</span></div>`
  }
}

function filterReminders(reminders) {
  if (currentView === 'reminders') return reminders.filter(r => !r.done && !r.missed)
  if (currentView === 'missed')     return reminders.filter(r => r.missed && !r.done)
  if (currentView === 'done')       return reminders.filter(r => r.done === true)
  return reminders
}

const typeColors = {
  important: '#c4501e', health: '#0a5c44', routine: '#0081a7', personal: '#6b4f8a', casual: '#a89a8a'
}

function renderReminders(allReminders) {
  const reminders = filterReminders(allReminders)
  const area      = document.getElementById('reminders-area')
  const count     = document.getElementById('reminder-count')

  count.textContent = reminders.length > 0 ? reminders.length : ''

  if (reminders.length === 0) {
    const labels = {
      reminders: 'No active reminders yet',
      missed:     'No missed reminders',
      done:       'Nothing marked done yet'
    }
    area.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
        </div>
        <p>${labels[currentView] || 'Nothing here'}</p>
        <span>Tap the mic button and speak</span>
      </div>`
    return
  }

  area.innerHTML = ''
  reminders.forEach((r, i) => {
    const time = r.datetime
      ? new Date(r.datetime).toLocaleString('en-US', {
          weekday: 'short', month: 'short', day: 'numeric',
          hour: 'numeric', minute: '2-digit'
        })
      : 'No time set'

    const card = document.createElement('div')
    card.className = `card${r.done ? ' is-done' : ''}`
    card.dataset.type = r.type
    card.style.animationDelay = `${i * 40}ms`
    card.innerHTML = `
      <div class="cdot" style="background:${typeColors[r.type] || '#aaa'}"></div>
      <div class="cbody">
        <div class="ctitle">${r.title}</div>
        <div class="csub">${time}${r.location ? ' · ' + r.location : ''}</div>
      </div>
      <div class="card-actions">
        <span class="tag tag-${r.type}">${r.type}</span>
        ${r.repeat !== 'none' ? `<span class="tag tag-rec">${r.repeat}</span>` : ''}
        ${!r.done && currentView !== 'missed' ? `
          <button class="done-btn" onclick="markDone('${r.id}')" title="Mark done">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </button>` : ''}
      </div>`
    area.appendChild(card)
  })
}

async function markDone(id) {
  await fetch(`${API_BASE}/reminders/${id}/done`, {
    method: 'PATCH',
    headers: { 'Authorization': `Bearer ${getToken()}` }
  })
  loadReminders()
}

// ─── Navigation ───────────────────────────────────────────────────────────────
function switchView(view) {
  currentView = view

  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'))
  const activeBtn = document.getElementById(`nav-${view}`)
  if (activeBtn) activeBtn.classList.add('active')

  const titles = { reminders: 'Reminders', missed: 'Missed', done: 'Done', settings: 'Settings' }
  document.getElementById('page-title').textContent = titles[view] || view

  const remArea       = document.getElementById('reminders-area')
  const settingsPanel = document.getElementById('settings-panel')

  if (view === 'settings') {
    remArea.style.display       = 'none'
    settingsPanel.style.display = 'block'
    document.getElementById('reminder-count').textContent = ''
    populateSettings()
  } else {
    remArea.style.display       = ''
    settingsPanel.style.display = 'none'
    loadReminders()
  }
}

// ─── Settings ────────────────────────────────────────────────────────────────
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

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') }
  } catch { return { ...DEFAULTS } }
}

function saveSettings() {
  const s = {
    morning:     document.getElementById('s-morning')?.value     || DEFAULTS.morning,
    evening:     document.getElementById('s-evening')?.value     || DEFAULTS.evening,
    night:       document.getElementById('s-night')?.value       || DEFAULTS.night,
    inABit:      parseInt(document.getElementById('s-in-a-bit')?.value)      || DEFAULTS.inABit,
    afterAWhile: parseInt(document.getElementById('s-after-a-while')?.value) || DEFAULTS.afterAWhile,
    vibration:   document.getElementById('vibration-toggle')?.classList.contains('on') ?? DEFAULTS.vibration,
    timezone:    document.getElementById('s-timezone')?.value || DEFAULTS.timezone
  }
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s))
}

function populateSettings() {
  const s = loadSettings()
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val }
  set('s-morning',      s.morning)
  set('s-evening',      s.evening)
  set('s-night',        s.night)
  set('s-in-a-bit',     s.inABit)
  set('s-after-a-while',s.afterAWhile)
  set('s-timezone',     s.timezone)
  const d1 = document.getElementById('s-in-a-bit-display')
  const d2 = document.getElementById('s-after-a-while-display')
  if (d1) d1.textContent = s.inABit
  if (d2) d2.textContent = s.afterAWhile
  const vt = document.getElementById('vibration-toggle')
  if (vt) { s.vibration ? vt.classList.add('on') : vt.classList.remove('on') }

  // ── Inject Account section once ──────────────────────────────────────────
  if (!document.getElementById('account-section')) {
    const panel = document.getElementById('settings-panel')
    const section = document.createElement('div')
    section.id = 'account-section'
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
        </div>` : ''}
      <div class="settings-item">
        <span>Sign out</span>
        <button
          onclick="logout()"
          style="padding:6px 16px;border-radius:8px;background:var(--mint);border:1.5px solid var(--border);color:var(--muted);font-size:12px;font-family:'DM Sans',sans-serif;cursor:pointer;transition:background 0.15s"
          onmouseover="this.style.background='var(--sage)'"
          onmouseout="this.style.background='var(--mint)'"
        >Sign out</button>
      </div>
    `
    // Insert at top of settings, before all other groups
    panel.insertBefore(section, panel.firstChild)
  }
}

function stepValue(id, delta) {
  const input   = document.getElementById(id)
  const display = document.getElementById(id + '-display')
  if (!input || !display) return
  const min = 1, max = 120
  let val = parseInt(input.value) + delta
  val = Math.max(min, Math.min(max, val))
  input.value = val
  display.textContent = val
  saveSettings()
  // haptic feedback on step
  if (loadSettings().vibration && navigator.vibrate) navigator.vibrate(30)
}

function toggleVibration() {
  const t = document.getElementById('vibration-toggle')
  t.classList.toggle('on')
  const isOn = t.classList.contains('on')
  if (isOn && navigator.vibrate) navigator.vibrate([80, 40, 80])
  saveSettings()
}

// ─── Clock (defined after DEFAULTS so loadSettings works) ───────────────────
function updateClock() {
  const s  = loadSettings()
  const tz = s.timezone || 'Asia/Kolkata'
  const now = new Date()
  const timeEl = document.getElementById('today-time')
  const tzEl   = document.getElementById('tz-badge')
  if (timeEl) timeEl.textContent = now.toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', second: '2-digit',
    hour12: true, timeZone: tz
  })
  if (tzEl) {
    const shortTz = now.toLocaleTimeString('en-US', { timeZoneName: 'short', timeZone: tz })
      .split(' ').pop()
    tzEl.textContent = shortTz
  }
}
updateClock()
setInterval(updateClock, 1000)

// Build a settings context string to inject into agent messages
function buildSettingsContext() {
  const s  = loadSettings()
  const tz = s.timezone || 'Asia/Kolkata'
  const now = new Date()
  const currentDateTime = now.toLocaleString('en-US', {
    timeZone: tz,
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true
  })
  return `[Current time: ${currentDateTime} | User preferences: timezone=${tz}, "morning"=${s.morning}, "evening"=${s.evening}, "night"=${s.night}, "in a bit"=${s.inABit} minutes, "after a while"=${s.afterAWhile} minutes]`
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Show demo banner at top of reminders area if in demo mode
  if (isDemo()) {
    const banner = document.createElement('div')
    banner.style.cssText = [
      'background:rgba(181,131,90,0.1)',
      'border:1px solid rgba(181,131,90,0.22)',
      'border-radius:10px',
      'padding:10px 14px',
      'margin-bottom:4px',
      'font-size:12px',
      'color:var(--muted)',
      'display:flex',
      'align-items:center',
      'gap:8px',
      'line-height:1.4'
    ].join(';')
    banner.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;color:var(--brown)">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <span>You're in demo mode.
        <a href="/login.html" style="color:var(--brown);font-weight:600;text-decoration:none">Create a free account</a>
        to keep your reminders.
      </span>`
    document.getElementById('reminders-area').before(banner)
  }

  loadReminders()
  initPush()
})