// ─── AUTH GUARD — runs before anything else ────────────────────────────────────
;(function () {
  if (!localStorage.getItem('scheduler_token')) {
    window.location.replace('/login.html')
  }
})()

// ─── CONFIG ───────────────────────────────────────────────────────────────────
const API_BASE        = 'https://adaptive-scheduler-x6nw.onrender.com'
const VAPID_PUBLIC_KEY = 'BLdUTJ82_k03z93xAJadQ2U58tp-V5ICr_g4Hf_20L6uJ0C9XDnLHxgux-UOJ-QjLMFzoTaP4oTwx5FktGWeSyY'

// ─── AUTH HELPERS ─────────────────────────────────────────────────────────────
function getToken()    { return localStorage.getItem('scheduler_token') || '' }
function getNickname() { return localStorage.getItem('scheduler_nickname') || 'You' }
function getEmail()    { return localStorage.getItem('scheduler_email') || '' }
function isDemo()      { return localStorage.getItem('scheduler_is_demo') === 'true' }

function getAuthHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${getToken()}`
  }
}

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
  const base64  = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return new Uint8Array([...rawData].map(c => c.charCodeAt(0)))
}

async function initPush() {
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

// ─── Date ─────────────────────────────────────────────────────────────────────
document.getElementById('today-date').textContent = new Date().toLocaleDateString('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
})

// ─── State ────────────────────────────────────────────────────────────────────
let mediaRecorder = null
let audioChunks   = []
let recording     = false
let agentMessages = []
let awaitingReply = false
let currentView   = 'reminders'

// ─── Elements ─────────────────────────────────────────────────────────────────
const micBtn       = document.getElementById('mic-btn')
const typeBtn      = document.getElementById('type-btn')
const typeArea     = document.getElementById('type-area')
const typeInput    = document.getElementById('type-input')
const typeSend     = document.getElementById('type-send')
const chatBubbles  = document.getElementById('chat-bubbles')
const overlay      = document.getElementById('overlay')
const btnCancel    = document.getElementById('btn-cancel')
const btnCancel2   = document.getElementById('btn-cancel-2')
const btnSave      = document.getElementById('btn-save')
const micToast     = document.getElementById('mic-toast')

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
    case 'recording':  micBtn.classList.add('recording');  break
    case 'processing':
    case 'thinking':   micBtn.classList.add('processing'); break
  }
}

// ─── Chat Bubbles ─────────────────────────────────────────────────────────────
function addBubble(text, role) {
  const wrap   = document.createElement('div')
  wrap.className = `bubble-wrap ${role}`
  const bubble = document.createElement('div')
  bubble.className   = `bubble bubble-${role}`
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
    const stream    = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder   = new MediaRecorder(stream)
    audioChunks     = []
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
    const res = await fetch(`${API_BASE}/transcribe`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` },
      body: formData
    })
    if (res.status === 401) { handle401(); return }
    const data       = await res.json()
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
  const cancelWords = ['cancel', 'stop', 'never mind', 'nevermind', 'forget it', 'nope', 'abort']
  if (cancelWords.some(w => text.toLowerCase().includes(w)) && agentMessages.length > 0) {
    resetConversation()
    setMicState('idle')
    return
  }

  addBubble(text, 'user')
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
    } else if (result.type === 'answer') {
      awaitingReply = false
      addBubble(result.text, 'agent')
      setMicState('idle')
      // Don't auto-reset — user might want to ask a follow-up question

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
const SAVE_BTN_LABEL  = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Save Reminder`

function showConfirmModal(extracted) {
  _pendingExtracted = extracted
  document.getElementById('field-title').value     = extracted.title    || ''
  document.getElementById('field-location').value  = extracted.location || ''
  document.getElementById('field-type').value      = extracted.type     || 'personal'
  document.getElementById('field-repeat').value    = extracted.repeat   || 'none'
  document.getElementById('field-datetime').value  = extracted.datetime
    ? extracted.datetime.slice(0, 16) : ''
  document.getElementById('field-pre-alert').value = extracted.pre_alert_minutes ?? ''
  document.getElementById('field-follow-up').value = extracted.follow_up_minutes ?? ''
  overlay.classList.add('show')

  // Tour step 3 — fires when modal opens after user recorded
  if (isDemo() && _tourStep === 2 && !_tourDone) {
    _removeTourUI()
    setTimeout(() => _showTourStep(3), 350)
  }
}

function closeModal() {
  overlay.classList.remove('show')
  resetConversation()
}

btnCancel.addEventListener('click',  closeModal)
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
    if (!res.ok) {
      const err = await res.json()
      alert(err.detail || 'Could not save.')
      return
    }
    const data = await res.json()
    if (data.status === 'saved') {
      overlay.classList.remove('show')
      resetConversation()
      await loadReminders()

      // Tour step 4 — fires after reminder saved and cards are rendered
      if (isDemo() && _tourStep === 3 && !_tourDone) {
        setTimeout(() => _showTourStep(4), 500)
      }
    }
  } catch (err) {
    alert('Could not save. Is the backend running?')
    console.error(err)
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
  if (currentView === 'missed')    return reminders.filter(r => r.missed && !r.done)
  if (currentView === 'done')      return reminders.filter(r => r.done === true)
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
      missed:    'No missed reminders',
      done:      'Nothing marked done yet'
    }
    const hint = currentView === 'reminders' ? 'Tap the mic button and speak' : ''
    area.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
        </div>
        <p>${labels[currentView] || 'Nothing here'}</p>
        ${hint ? `<span>${hint}</span>` : ''}
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

    const isDemoVisitor = r.is_demo_reminder === true
    const card = document.createElement('div')
    card.className      = `card${r.done ? ' is-done' : ''}${isDemo() ? ' demo-reminder' : ''}${isDemoVisitor ? ' demo-visitor-card' : ''}`
    card.dataset.type   = r.type
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
  const demoBanner    = document.getElementById('demo-banner')

  if (view === 'settings') {
    remArea.style.display       = 'none'
    settingsPanel.style.display = 'block'
    document.getElementById('reminder-count').textContent = ''
    if (demoBanner) demoBanner.style.display = 'none'
    populateSettings()
  } else {
    remArea.style.display       = ''
    settingsPanel.style.display = 'none'
    if (demoBanner) demoBanner.style.display = view === 'reminders' ? 'flex' : 'none'
    loadReminders()
  }
}

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

function loadSettings() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') } }
  catch { return { ...DEFAULTS } }
}

function saveSettings() {
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

function populateSettings() {
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

function stepValue(id, delta) {
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

function toggleVibration() {
  const t = document.getElementById('vibration-toggle')
  t.classList.toggle('on')
  const isOn = t.classList.contains('on')
  if (isOn && navigator.vibrate) navigator.vibrate([80, 40, 80])
  saveSettings()
}

// ─── Clock ────────────────────────────────────────────────────────────────────
function updateClock() {
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
updateClock()
setInterval(updateClock, 1000)

function buildSettingsContext() {
  const s   = loadSettings()
  const tz  = s.timezone || 'Asia/Kolkata'
  const now = new Date()
  const currentDateTime = now.toLocaleString('en-US', {
    timeZone: tz, weekday: 'long', year: 'numeric', month: 'long',
    day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true
  })
  return `[Current time: ${currentDateTime} | User preferences: timezone=${tz}, "morning"=${s.morning}, "evening"=${s.evening}, "night"=${s.night}, "in a bit"=${s.inABit} minutes, "after a while"=${s.afterAWhile} minutes]`
}

// ─── DEMO TOUR ────────────────────────────────────────────────────────────────
let _tourStep = 0
let _tourDone = localStorage.getItem('demo_tour_done') === 'true'
let _tourEl   = null
let _spotEl   = null

// 8 steps — steps 3 and 4 are auto-triggered by events
const TOUR_STEPS = [
  {
    id: 1,
    title: '👋 Welcome to Scheduler',
    text:  'A smart reminder app that understands plain language. Quick tour — one minute.',
    target: null,
    next: 'Start tour →',
    skip: 'Skip tour'
  },
  {
    id: 2,
    title: '🎤 Record a reminder',
    text:  'Tap the mic and speak — try "Remind me to drink water in 30 minutes"',
    target: '#mic-btn',
    next: 'Try it now!',
    isAction: true
  },
  {
    id: 3,
    title: '✏️ Review the details',
    text:  'AI filled in what you said. Edit anything, then tap Save.',
    target: null,
    next: 'Got it',
    waitForSave: true,
    autoTrigger: true
  },
  {
    id: 4,
    title: '✅ Mark it done',
    text:  'Tap ✓ when you\'ve done it. Or tap Done in the notification.',
    target: '.done-btn',
    next: 'Next →',
    autoTrigger: true
  },
  {
    id: 5,
    title: '⚠️ Missed',
    text:  'Reminders you didn\'t act on within an hour show up here.',
    target: '#nav-missed',
    next: 'Next →'
  },
  {
    id: 6,
    title: '✓ Done',
    text:  'Everything you\'ve completed lives here.',
    target: '#nav-done',
    next: 'Next →'
  },
  {
    id: 7,
    title: '⚙️ Settings',
    text:  'Set your timezone and what "morning" or "in a bit" means to you.',
    target: '#nav-settings',
    next: 'Next →'
  },
  {
    id: 8,
    title: '🎉 That\'s it!',
    text:  'Create a free account to keep your reminders and get notifications.',
    target: null,
    next: 'Sign up free →',
    nextHref: '/login.html',
    skip: 'Keep exploring'
  }
]

function _injectDemoStyles() {
  if (document.getElementById('demo-styles')) return
  const style = document.createElement('style')
  style.id = 'demo-styles'
  style.textContent = `
    /* ── Demo reminder card (owner's view of demo users' reminders) ─────── */
    .card.demo-visitor-card {
      background: rgba(221,161,94,0.07);
      border: 1.5px dashed rgba(221,161,94,0.45);
    }
    .demo-visitor-badge {
      font-family: 'DM Mono', monospace;
      font-size: 8px;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      color: var(--brown);
      background: rgba(221,161,94,0.15);
      border: 1px solid rgba(221,161,94,0.3);
      border-radius: 20px;
      padding: 2px 7px;
      flex-shrink: 0;
    }

    /* ── Demo reminder card ──────────────────────────────────────────────── */
    .card.demo-reminder {
      background: rgba(221,161,94,0.06);
      border-color: rgba(221,161,94,0.35);
    }
    .demo-badge {
      font-family: 'DM Mono', monospace;
      font-size: 8.5px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--brown);
      background: rgba(221,161,94,0.18);
      border: 1px solid rgba(221,161,94,0.3);
      border-radius: 20px;
      padding: 2px 8px;
      flex-shrink: 0;
    }

    /* ── Tour overlay & spotlight ────────────────────────────────────────── */
    .tour-dim {
      position: fixed;
      inset: 0;
      background: rgba(74,53,32,0.62);
      z-index: 199;
      pointer-events: all;
    }
    .tour-spotlight {
      position: fixed;
      border-radius: 14px;
      box-shadow: 0 0 0 9999px rgba(74,53,32,0.62);
      z-index: 199;
      pointer-events: none;
      transition: all 0.28s ease;
    }

    /* ── Tour panel ──────────────────────────────────────────────────────── */
    .tour-panel {
      position: fixed;
      left: 16px;
      right: 16px;
      bottom: calc(68px + 14px + 14px);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 13px 15px 12px;
      z-index: 200;
      box-shadow: 0 8px 40px rgba(74,53,32,0.18);
      animation: tourPanelIn 0.25s ease both;
      pointer-events: all;
    }
    .tour-panel.tour-center {
      bottom: auto;
      top: 50%;
      left: 50%;
      right: auto;
      width: calc(100% - 48px);
      max-width: 360px;
      transform: translate(-50%, -50%);
    }
    @keyframes tourPanelIn {
      from { opacity:0; transform:translateY(10px) }
      to   { opacity:1; transform:translateY(0) }
    }
    .tour-panel.tour-center {
      animation: tourCenterIn 0.25s ease both;
    }
    @keyframes tourCenterIn {
      from { opacity:0; transform:translate(-50%,-46%) scale(0.96) }
      to   { opacity:1; transform:translate(-50%,-50%) scale(1) }
    }

    .tour-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
    }
    .tour-counter {
      font-family: 'DM Mono', monospace;
      font-size: 10px;
      color: var(--muted);
      letter-spacing: 0.06em;
    }
    .tour-skip-btn {
      font-family: 'DM Sans', sans-serif;
      font-size: 12px;
      color: var(--muted);
      background: none;
      border: none;
      cursor: pointer;
      padding: 2px 0;
    }
    .tour-title {
      font-family: 'DM Sans', sans-serif;
      font-weight: 600;
      font-size: 13.5px;
      color: var(--text);
      margin-bottom: 4px;
    }
    .tour-text {
      font-family: 'DM Sans', sans-serif;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
      margin-bottom: 11px;
    }
    .tour-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .tour-next-btn {
      flex: 1;
      padding: 9px 14px;
      border-radius: 11px;
      background: var(--brown);
      color: var(--cream);
      border: none;
      font-family: 'DM Sans', sans-serif;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      transition: background 0.15s;
    }
    .tour-next-btn:hover { background: #c48a4a; }

    /* ── Done button pulse on step 4 ─────────────────────────────────────── */
    .tour-done-pulse {
      animation: donePulse 1.2s ease-in-out 5;
    }
    @keyframes donePulse {
      0%,100% { box-shadow: none; }
      50%      { box-shadow: 0 0 0 5px rgba(221,161,94,0.45); border-radius: 8px; }
    }
  `
  document.head.appendChild(style)
}

function setupDemoMode() {
  if (!isDemo()) return
  _injectDemoStyles()

  // Start tour if not yet completed
  if (!_tourDone) {
    setTimeout(() => _showTourStep(1), 700)
  }
}

function _showTourStep(id) {
  _removeTourUI()
  _tourStep = id

  const step      = TOUR_STEPS.find(s => s.id === id)
  if (!step) return

  const isNavTarget = !!(step.target && step.target.startsWith('#nav-'))
  const hasTarget   = !!(step.target && document.querySelector(step.target))
  const isCenter    = !hasTarget  // welcome / end / auto-trigger with no target → center card

  const totalSteps = TOUR_STEPS.length

  // ── Spotlight or dim overlay ───────────────────────────────────────────
  if (hasTarget) {
    const target = document.querySelector(step.target)
    const rect   = target.getBoundingClientRect()
    const pad    = isNavTarget ? 3 : 8
    _spotEl = document.createElement('div')
    _spotEl.className = 'tour-spotlight'
    _spotEl.style.top    = (rect.top    - pad) + 'px'
    _spotEl.style.left   = (rect.left   - pad) + 'px'
    _spotEl.style.width  = (rect.width  + pad * 2) + 'px'
    _spotEl.style.height = (rect.height + pad * 2) + 'px'
    document.body.appendChild(_spotEl)
  } else {
    _spotEl = document.createElement('div')
    _spotEl.className = 'tour-dim'
    document.body.appendChild(_spotEl)
  }

  // ── Panel ──────────────────────────────────────────────────────────────
  _tourEl = document.createElement('div')
  _tourEl.className = `tour-panel${isCenter ? ' tour-center' : ''}`

  // Skip button — only in the top-right meta area, only for steps that define one
  const skipHtml = step.skip
    ? `<button class="tour-skip-btn" onclick="endTour()">${step.skip}</button>`
    : '<span></span>'

  // Next button action
  let nextAction
  if (step.isAction)       nextAction = `onclick="_pauseForAction()"`
  else if (step.waitForSave) nextAction = `onclick="_waitForSave()"`
  else if (step.nextHref)  nextAction = `onclick="endTour();window.location.href='${step.nextHref}'"`
  else                     nextAction = `onclick="_nextTourStep()"`

  // Step 8 end card: two buttons side by side
  const actionsHtml = id === 8
    ? `<div class="tour-actions">
         <button class="tour-skip-btn" onclick="endTour()">Keep exploring</button>
         <button class="tour-next-btn" onclick="endTour();window.location.href='/login.html'">Sign up free →</button>
       </div>`
    : `<div class="tour-actions">
         <button class="tour-next-btn" ${nextAction}>${step.next}</button>
       </div>`

  _tourEl.innerHTML = `
    <div class="tour-meta">
      <span class="tour-counter">${id} of ${totalSteps}</span>
      ${id !== 8 ? skipHtml : '<span></span>'}
    </div>
    <div class="tour-title">${step.title}</div>
    <div class="tour-text">${step.text}</div>
    ${actionsHtml}
  `
  document.body.appendChild(_tourEl)

  // Pulse the done button on step 4
  if (id === 4) {
    setTimeout(() => {
      const doneBtn = document.querySelector('.done-btn')
      if (doneBtn) {
        doneBtn.classList.add('tour-done-pulse')
        setTimeout(() => doneBtn.classList.remove('tour-done-pulse'), 6000)
      }
    }, 100)
  }
}

function _nextTourStep() {
  const nextId = _tourStep + 1
  const next   = TOUR_STEPS.find(s => s.id === nextId)
  if (!next)            { endTour(); return }
  // Auto-trigger steps fire from events — skip when navigating manually
  if (next.autoTrigger) { _tourStep = nextId; _nextTourStep(); return }
  _showTourStep(nextId)
}

function _pauseForAction() {
  // User tapped "Try it now!" — dismiss overlay so they can tap mic
  // _tourStep stays at 2; step 3 fires when the confirm modal opens
  _removeTourUI()
  showToast('Tap the mic and say a reminder!')
}

function _waitForSave() {
  // User tapped "Got it" on the review step — just close the panel
  // _tourStep stays at 3; step 4 fires from btnSave after reminder is saved
  _removeTourUI()
}

function endTour() {
  _removeTourUI()
  _tourDone = true
  _tourStep = 0
  localStorage.setItem('demo_tour_done', 'true')
}

function _removeTourUI() {
  if (_tourEl) { _tourEl.remove(); _tourEl = null }
  if (_spotEl) { _spotEl.remove(); _spotEl = null }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
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