// ─── CONFIG ───────────────────────────────────────────────────────────────────
const API_BASE = 'https://adaptive-scheduler-x6nw.onrender.com'
// const API_BASE = 'http://localhost:8000'

const VAPID_PUBLIC_KEY = 'BLdUTJ82_k03z93xAJadQ2U58tp-V5ICr_g4Hf_20L6uJ0C9XDnLHxgux-UOJ-QjLMFzoTaP4oTwx5FktGWeSyY'

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
    await fetch(`${API_BASE}/subscribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subscription)
    })
  } catch (err) {
    console.error('push setup error:', err)
  }
}

initPush()

// ─── Date & Live Clock ───────────────────────────────────────────────────────
document.getElementById('today-date').textContent = new Date().toLocaleDateString('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
})

function updateClock() {
  const el = document.getElementById('today-time')
  if (el) el.textContent = new Date().toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true
  })
}
updateClock()
setInterval(updateClock, 1000)

// ─── State ────────────────────────────────────────────────────────────────────
let mediaRecorder = null
let audioChunks = []
let recording = false
let agentMessages = []
let awaitingReply = false
let currentView = 'reminders'

// ─── Elements ─────────────────────────────────────────────────────────────────
const micBtn     = document.getElementById('mic-btn')
const typeBtn    = document.getElementById('type-btn')
const typeArea   = document.getElementById('type-area')
const typeInput  = document.getElementById('type-input')
const typeSend   = document.getElementById('type-send')
const chatBubbles = document.getElementById('chat-bubbles')
const overlay    = document.getElementById('overlay')
const btnCancel  = document.getElementById('btn-cancel')
const btnCancel2 = document.getElementById('btn-cancel-2')
const btnSave    = document.getElementById('btn-save')
const micToast   = document.getElementById('mic-toast')

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
    const res = await fetch(`${API_BASE}/transcribe`, { method: 'POST', body: formData })
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
  addBubble(text, 'user')
  agentMessages.push({ role: 'user', content: text })
  setMicState('thinking')
  awaitingReply = false

  try {
    const res = await fetch(`${API_BASE}/agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: agentMessages })
    })
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
function showConfirmModal(extracted) {
  document.getElementById('field-title').value    = extracted.title    || ''
  document.getElementById('field-location').value = extracted.location || ''
  document.getElementById('field-type').value     = extracted.type     || 'casual'
  document.getElementById('field-repeat').value   = extracted.repeat   || 'none'
  document.getElementById('field-datetime').value = extracted.datetime
    ? extracted.datetime.slice(0, 16) : ''
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
    datetime:     document.getElementById('field-datetime').value || null,
    location:     document.getElementById('field-location').value || null,
    type:         document.getElementById('field-type').value,
    repeat:       document.getElementById('field-repeat').value,
    participants: []
  }

  try {
    const res = await fetch(`${API_BASE}/reminders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reminder)
    })
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
    btnSave.textContent = 'Save Reminder'
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
    const res = await fetch(`${API_BASE}/reminders`)
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
  if (currentView === 'reminders') return reminders.filter(r => !r.done)
  if (currentView === 'recurring')  return reminders.filter(r => !r.done && r.repeat !== 'none')
  if (currentView === 'done')       return reminders.filter(r => r.done === true)
  return reminders
}

const typeColors = {
  meeting: '#0081a7', medication: '#0a5c44', task: '#c4501e', casual: '#a89a8a'
}

function renderReminders(allReminders) {
  const reminders = filterReminders(allReminders)
  const area      = document.getElementById('reminders-area')
  const count     = document.getElementById('reminder-count')

  count.textContent = reminders.length > 0 ? reminders.length : ''

  if (reminders.length === 0) {
    const labels = {
      reminders: 'No active reminders yet',
      recurring:  'No recurring reminders',
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
        ${!r.done ? `
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
  await fetch(`${API_BASE}/reminders/${id}/done`, { method: 'PATCH' })
  loadReminders()
}

// ─── Navigation ───────────────────────────────────────────────────────────────
function switchView(view) {
  currentView = view

  // Update nav active state
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'))
  const activeBtn = document.getElementById(`nav-${view}`)
  if (activeBtn) activeBtn.classList.add('active')

  // Update page title
  const titles = { reminders: 'Reminders', recurring: 'Recurring', done: 'Done', settings: 'Settings' }
  document.getElementById('page-title').textContent = titles[view] || view

  // Show/hide panels
  const remArea      = document.getElementById('reminders-area')
  const settingsPanel = document.getElementById('settings-panel')

  if (view === 'settings') {
    remArea.style.display      = 'none'
    settingsPanel.style.display = 'block'
    document.getElementById('reminder-count').textContent = ''
  } else {
    remArea.style.display      = ''
    settingsPanel.style.display = 'none'
    loadReminders()
  }
}

// ─── Settings Toggle ──────────────────────────────────────────────────────────
function toggleNotif() {
  const t = document.getElementById('notif-toggle')
  t.classList.toggle('on')
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadReminders()
})