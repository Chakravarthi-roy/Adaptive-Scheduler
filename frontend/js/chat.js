import { API_BASE } from './config.js'
import { getToken, getAuthHeaders, handle401 } from './auth.js'
import { buildSettingsContext } from './settings.js'
import { loadReminders } from './reminders.js'
// NOTE: circular import — modal.js imports resetConversation/continueSideAction/
// lastResultIntent from this file, and this file imports showConfirmModal from
// modal.js. This is safe in ES modules as long as neither side uses the other's
// binding at the top level of the module (only inside function bodies, which
// is the case here — everything below is called later, at event time, well
// after both modules have finished loading).
import { showConfirmModal } from './modal.js'
import { micBtn, typeBtn, typeArea, typeInput, typeSend, chatBubbles, chatCloseBtn, micToast } from './dom.js'

// ─── State ────────────────────────────────────────────────────────────────────
let mediaRecorder = null
let audioChunks   = []
let recording     = false
export let agentMessages = []
export let awaitingReply = false
export let awaitingCloseConfirmation = false   // true right after an 'answer' — watching for thanks/no

// The whole-conversation intent the server classified from the FIRST message
// (e.g. "move my meeting to 5pm" stays "update" for the whole conversation).
// Tracked so the modal/update/delete handlers can tell "the thing this
// conversation was actually about just finished" apart from "a detour
// happened along the way (e.g. creating a replacement while updating)".
export let lastResultIntent = null

// ─── Toast ────────────────────────────────────────────────────────────────────
let toastTimer = null
export function showToast(msg) {
  micToast.textContent = msg
  micToast.classList.add('show')
  clearTimeout(toastTimer)
  if (msg) toastTimer = setTimeout(() => micToast.classList.remove('show'), 3000)
}

// ─── Mic State ────────────────────────────────────────────────────────────────
export function setMicState(state) {
  micBtn.classList.remove('recording', 'processing')
  typeBtn.style.display = awaitingReply ? 'flex' : 'none'
  switch (state) {
    case 'recording':  micBtn.classList.add('recording');  break
    case 'processing':
    case 'thinking':   micBtn.classList.add('processing'); break
  }
}

// ─── Chat Bubbles ─────────────────────────────────────────────────────────────
export function addBubble(text, role) {
  const wrap   = document.createElement('div')
  wrap.className = `bubble-wrap ${role}`
  const bubble = document.createElement('div')
  bubble.className   = `bubble bubble-${role}`
  bubble.textContent = text
  wrap.appendChild(bubble)
  chatBubbles.appendChild(wrap)
  chatBubbles.scrollTop = chatBubbles.scrollHeight
  updateChatPanelVisibility()
}

export function clearBubbles() {
  chatBubbles.innerHTML = ''
  updateChatPanelVisibility()
}

// Opaque backdrop + close button both track "is there an actual conversation
// on screen right now" — same condition, one helper, called after every
// bubble add/clear so they can never drift out of sync with each other.
function updateChatPanelVisibility() {
  const hasContent = chatBubbles.children.length > 0
  chatBubbles.classList.toggle('active', hasContent)
  chatCloseBtn.style.display = hasContent ? 'flex' : 'none'
}

chatCloseBtn.addEventListener('click', () => resetConversation())

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

// Purely local detection — same reasoning as the intent router: comparing a
// string against a short word list costs microseconds and doesn't need a
// round-trip to the LLM just to notice someone said "thanks."
const _THANKS_WORDS = ['thank you', 'thanks', 'thankyou', 'thnx', 'tq', 'thx']
const _CLOSE_WORDS  = ['no', 'nope', 'nah', "that's all", 'thats all', "i'm good", 'im good', 'nothing else', 'no thanks', 'all good']

function _isThanks(t) {
  const lower = t.toLowerCase().trim()
  return _THANKS_WORDS.some(w => lower === w || lower.startsWith(w + ' ') || lower.startsWith(w + '!'))
}
function _isCloseSignal(t) {
  const lower = t.toLowerCase().trim()
  return _CLOSE_WORDS.some(w => lower === w || lower.startsWith(w + ' ') || lower.startsWith(w + '!'))
}

export async function handleTextInput(text) {
  // If we just answered a question and are watching for "thanks"/"no", handle
  // it locally — no need to burn a backend call on a closing pleasantry.
  // Anything that ISN'T a clear thanks/close signal falls through and is
  // treated as a genuine follow-up question, sent to the backend as normal.
  if (awaitingCloseConfirmation) {
    if (_isThanks(text)) {
      addBubble(text, 'user')
      addBubble("You're welcome! Anything else you'd like to know?", 'agent')
      // stay in awaitingCloseConfirmation — still watching for a close signal
      return
    }
    if (_isCloseSignal(text)) {
      addBubble(text, 'user')
      addBubble('Okay, glad I could help! 👋', 'agent')
      awaitingCloseConfirmation = false
      setTimeout(resetConversation, 1400)
      return
    }
    // real follow-up question — stop watching for a close signal, proceed normally
    awaitingCloseConfirmation = false
  }

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

  await _sendToAgent()
}

// Fires the actual /agent request and hands the response to processAgentResult.
// Shared by handleTextInput AND continueSideAction below — the "resume the
// original task after a detour" flow needs the exact same response handling,
// just without a fresh user bubble/message being typed first.
async function _sendToAgent() {
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
    processAgentResult(result)
  } catch (err) {
    console.error(err)
    awaitingReply = false
    setMicState('idle')
    alert('Something went wrong — check the console.')
  }
}

export function processAgentResult(result) {
  lastResultIntent = result.intent || lastResultIntent

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
    // Don't auto-reset — user might want to ask a follow-up. But now we
    // watch for a thanks/no so the chat has an actual way to close instead
    // of just sitting open forever with no resolution.
    awaitingCloseConfirmation = true

  } else if (result.type === 'updated') {
    awaitingReply = false
    addBubble(result.text, 'agent')
    setMicState('idle')
    loadReminders()
    // Only reset if updating was what this whole conversation was actually
    // about. If it was a detour (e.g. deleting something while the real
    // goal was an update), keep the conversation open and pick back up.
    if (lastResultIntent === 'update') {
      setTimeout(resetConversation, 1800)
    } else {
      setTimeout(() => continueSideAction(`${result.text}`), 1200)
    }
  } else if (result.type === 'deleted') {
    awaitingReply = false
    addBubble(result.text, 'agent')
    setMicState('idle')
    loadReminders()
    if (lastResultIntent === 'delete') {
      setTimeout(resetConversation, 1800)
    } else {
      setTimeout(() => continueSideAction(`${result.text}`), 1200)
    }
  } else if (result.type === 'error') {
    awaitingReply = false
    addBubble(result.text, 'agent')
    setMicState('idle')
  }
}

// After a mid-conversation detour (create/delete spawned while doing
// something else) completes, nudge the agent to resume the ORIGINAL task
// instead of just leaving the conversation hanging.
export async function continueSideAction(noteText) {
  agentMessages.push({ role: 'user', content: `[${noteText} Continue with what we were doing before.]` })
  setMicState('thinking')
  await _sendToAgent()
}

export function resetConversation() {
  agentMessages = []
  awaitingReply = false
  awaitingCloseConfirmation = false
  lastResultIntent = null
  clearBubbles()
  setMicState('idle')
}