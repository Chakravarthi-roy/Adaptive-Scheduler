// ─── CONFIG ─────────────────────────────────────────────
const API_BASE = 'https://adaptive-scheduler-api.onrender.com' // 👈 update this after deploying backend
// const API_BASE = 'http://localhost:8000' // use this for local dev
// ────────────────────────────────────────────────────────

// VAPID public key
const VAPID_PUBLIC_KEY = 'BLdUTJ82_k03z93xAJadQ2U58tp-V5ICr_g4Hf_20L6uJ0C9XDnLHxgux-UOJ-QjLMFzoTaP4oTwx5FktGWeSyY'

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return new Uint8Array([...rawData].map(c => c.charCodeAt(0)))
}

async function initPush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    console.log('push not supported')
    return
  }
  try {
    const reg = await navigator.serviceWorker.register('./sw.js')
    console.log('service worker registered')
    await navigator.serviceWorker.ready
    console.log('service worker ready')
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') {
      console.log('notification permission denied')
      return
    }
    const subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
    })
    await fetch(`${API_BASE}/subscribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subscription)
    })
    console.log('push subscription saved')
  } catch (err) {
    console.error('push setup error:', err)
  }
}

initPush()

// set today's date
const dateEl = document.getElementById('today-date')
dateEl.textContent = new Date().toLocaleDateString('en-US', {
  weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
})

// mic state
const micBtn = document.getElementById('mic-btn')
const micLabel = document.getElementById('mic-label')
const micStatus = document.getElementById('mic-status')
let mediaRecorder = null
let audioChunks = []
let recording = false

function setMicState(state) {
  micBtn.classList.remove('recording', 'processing')
  switch(state) {
    case 'idle':
      micLabel.textContent = 'tap to speak'
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
      micStatus.textContent = '🧠 extracting reminder'
      break
  }
}

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

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data)
    }

    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' })
      await sendToBackend(audioBlob)
      stream.getTracks().forEach(t => t.stop())
    }

    mediaRecorder.start()
    recording = true
    setMicState('recording')

  } catch (err) {
    alert('Microphone access denied. Please allow mic access and try again.')
    console.error(err)
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  }
  recording = false
  setMicState('processing')
}

async function sendToBackend(audioBlob) {
  try {
    setMicState('processing')
    console.log('audio blob size:', audioBlob.size, 'bytes')

    if (audioBlob.size < 1000) {
      setMicState('idle')
      alert('Recording too short — please speak for at least 2 seconds.')
      return
    }

    const formData = new FormData()
    formData.append('audio', audioBlob, 'recording.webm')

    console.log('sending to Whisper...')
    const transcribeRes = await fetch(`${API_BASE}/transcribe`, {
      method: 'POST',
      body: formData
    })
    const rawText = await transcribeRes.text()
    console.log('raw response:', rawText)
    const transcribeData = JSON.parse(rawText)
    const transcript = transcribeData.transcript
    console.log('transcript:', transcript)

    if (!transcript || transcript.trim() === '') {
      setMicState('idle')
      alert('Could not hear anything. Try speaking louder or closer to the mic.')
      return
    }

    setMicState('thinking')
    console.log('extracting intent...')
    const extractRes = await fetch(`${API_BASE}/extract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript })
    })
    const extracted = await extractRes.json()
    console.log('extracted:', extracted)

    setMicState('idle')
    showConfirmModal(transcript, extracted)

  } catch (err) {
    console.error('sendToBackend error:', err)
    setMicState('idle')
    alert('Something went wrong — check the console for details.')
  }
}

// modal
const overlay = document.getElementById('overlay')
const btnCancel = document.getElementById('btn-cancel')
const btnSave = document.getElementById('btn-save')
const modalHeard = document.getElementById('modal-heard')

function showConfirmModal(transcript, extracted) {
  micLabel.textContent = 'tap to speak'
  modalHeard.textContent = `"${transcript}"`
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

btnCancel.addEventListener('click', () => overlay.classList.remove('show'))

btnSave.addEventListener('click', async () => {
  const title = document.getElementById('field-title').value
  if (!title.trim()) {
    alert('Title cannot be empty.')
    return
  }
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
      loadReminders()
    }
  } catch (err) {
    alert('Could not save. Is the backend running?')
  }
})

async function loadReminders() {
  try {
    const res = await fetch(`${API_BASE}/reminders`)
    const reminders = await res.json()
    renderReminders(reminders)
  } catch (err) {
    console.error('could not load reminders:', err)
  }
}

function renderReminders(reminders) {
  const area = document.getElementById('reminders-area')
  if (reminders.length === 0) {
    area.innerHTML = '<div class="empty-state">No reminders yet. Tap the mic and speak.</div>'
    return
  }
  const typeColors = {
    meeting: '#0081a7',
    medication: '#0a5c44',
    task: '#c4501e',
    casual: '#aaa'
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

loadReminders()