// ─── CONFIG ──────────────────────────────────────────────────────────────────
const API_BASE = 'https://adaptive-scheduler-x6nw.onrender.com'
// const API_BASE = 'http://localhost:8000'
// ─────────────────────────────────────────────────────────────────────────────

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

// ─── Date ─────────────────────────────────────────────────────────────────────
document.getElementById('today-date').textContent = new Date().toLocaleDateString('en-US', {
  weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
})

// ─── State ────────────────────────────────────────────────────────────────────
let mediaRecorder = null
let audioChunks = []
let recording = false
let agentMessages = []
let awaitingReply = false
let currentView = 'reminders'  // 'reminders', 'recurring', 'done'

// ─── Elements ─────────────────────────────────────────────────────────────────
const micBtn = document.getElementById('mic-btn')
const micLabel = document.getElementById('mic-label')
const micStatus = document.getElementById('mic-status')
const typeBtn = document.getElementById('type-btn')
const typeArea = document.getElementById('type-area')
const typeInput = document.getElementById('type-input')
const typeSend = document.getElementById('type-send')
const chatBubbles = document.getElementById('chat-bubbles')
const overlay = document.getElementById('overlay')
const btnCancel = document.getElementById('btn-cancel')
const btnSave = document.getElementById('btn-save')

// ─── Mic State ────────────────────────────────────────────────────────────────
function setMicState(state) {
  micBtn.classList.remove('recording', 'processing')
  typeBtn.style.display = awaitingReply ? 'flex' : 'none'
  switch (state) {
    case 'idle':
      micLabel.textContent = awaitingReply ? 'tap to reply' : 'tap to speak'
      micStatus.textContent = ''
      break
    case 'recording':
      micBtn.classList.add('recording')
      micLabel.textContent = 'recording... tap to stop'
      micStatus.textContent = '🔴 mic is on'
      break
    case 'processing':
      micBtn.classList.add('processing')
      micLabel.textContent = 'transcribing...'
      micStatus.textContent = '⏳ sending to Whisper'
      break
    case 'thinking':
      micBtn.classList.add('processing')
      micLabel.textContent = 'thinking...'
      micStatus.textContent = '🧠 agent is working'
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

function clearBubbles() {
  chatBubbles.innerHTML = ''
}

// ─── Recording ────────────────────────────────────────────────────────────────
micBtn.addEventListener('click', async () => {
  if (!recording) {
    await startRecording()
  } else {
    stopRecording()
  }
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
  typeInput.focus()
})

typeSend.addEventListener('click', () => sendTypedReply())
typeInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendTypedReply()
})

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
      // reminder deleted — show confirmation bubble and refresh list
      awaitingReply = false
      addBubble(result.text, 'agent')
      setMicState('idle')
      loadReminders()
      // clear conversation immediately
      resetConversation()

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
  document.getElementById('field-title').value = extracted.title || ''
  document.getElementById('field-location').value = extracted.location || ''
  document.getElementById('field-type').value = extracted.type || 'casual'
  document.getElementById('field-repeat').value = extracted.repeat || 'none'
  if (extracted.datetime) {
    document.getElementById('field-datetime').value = extracted.datetime.slice(0, 16)
  } else {
    document.getElementById('field-datetime').value = ''
  }
  overlay.classList.add('show')
}

btnCancel.addEventListener('click', () => {
  overlay.classList.remove('show')
  resetConversation()
})

btnSave.addEventListener('click', async () => {
  const title = document.getElementById('field-title').value
  if (!title.trim()) { alert('Title cannot be empty.'); return }

  // disable button to prevent double click
  btnSave.disabled = true
  btnSave.textContent = 'Saving...'

  const reminder = {
    title,
    datetime: document.getElementById('field-datetime').value || null,
    location: document.getElementById('field-location').value || null,
    type: document.getElementById('field-type').value,
    repeat: document.getElementById('field-repeat').value,
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
    btnSave.textContent = 'Save reminder'
  }
})

function resetConversation() {
  agentMessages = []
  awaitingReply = false
  clearBubbles()
  setMicState('idle')
}

// ─── Reminders ────────────────────────────────────────────────────────────────
async function loadReminders() {
  try {
    const res = await fetch(`${API_BASE}/reminders`)
    const allReminders = await res.json()
    renderReminders(allReminders)
  } catch (err) {
    console.error('could not load reminders:', err)
  }
}

function filterReminders(reminders) {
  if (currentView === 'reminders') {
    // Active reminders: not done
    return reminders.filter(r => !r.done)
  } else if (currentView === 'recurring') {
    // Recurring reminders: repeat != 'none' and not done
    return reminders.filter(r => !r.done && r.repeat !== 'none')
  } else if (currentView === 'done') {
    // Completed reminders: done = true
    return reminders.filter(r => r.done)
  }
  return reminders
}

function renderReminders(allReminders) {
  const reminders = filterReminders(allReminders)
  const area = document.getElementById('reminders-area')
  
  if (reminders.length === 0) {
    area.innerHTML = '<div class="empty-state">No reminders yet. Tap the mic and speak.</div>'
    return
  }
  
  const typeColors = {
    meeting: '#0081a7', medication: '#0a5c44', task: '#c4501e', casual: '#aaa'
  }
  area.innerHTML = ''
  reminders.forEach(r => {
    const time = r.datetime
      ? new Date(r.datetime).toLocaleString('en-US', {
          weekday: 'short', month: 'short', day: 'numeric',
          hour: 'numeric', minute: '2-digit'
        })
      : 'No time set'
    const card = document.createElement('div')
    card.className = 'card'
    card.innerHTML = `
      <div class="cdot" style="background:${typeColors[r.type] || '#aaa'}"></div>
      <div class="cbody">
        <div class="ctitle">${r.title}</div>
        <div class="csub">${time}${r.location ? ' · ' + r.location : ''}</div>
      </div>
      <div style="display:flex;gap:5px;align-items:center">
        <span class="tag tag-${r.type}">${r.type}</span>
        ${r.repeat !== 'none' ? `<span class="tag tag-rec">${r.repeat}</span>` : ''}
        <button onclick="markDone('${r.id}')" style="background:none;border:none;cursor:pointer;font-size:16px;" title="Mark done">✓</button>
      </div>
    `
    area.appendChild(card)
  })
}

async function markDone(id) {
  await fetch(`${API_BASE}/reminders/${id}/done`, { method: 'PATCH' })
  loadReminders()
}

// ─── Sidebar Navigation ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadReminders()
  const navItems = document.querySelectorAll('.nav-item')
  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault()
      const view = item.textContent.toLowerCase()
      
      // Update active state
      navItems.forEach(ni => ni.classList.remove('active'))
      item.classList.add('active')
      
      // Update view and title
      if (view === 'reminders') {
        currentView = 'reminders'
        document.querySelector('.page-title').textContent = 'Reminders'
      } else if (view === 'recurring') {
        currentView = 'recurring'
        document.querySelector('.page-title').textContent = 'Recurring'
      } else if (view === 'done') {
        currentView = 'done'
        document.querySelector('.page-title').textContent = 'Done'
      } else if (view === 'settings') {
        currentView = 'settings'
        document.querySelector('.page-title').textContent = 'Settings'
      }
    })
  })
})

loadReminders()