import { API_BASE } from './config.js'
import { getAuthHeaders, handle401, isDemo } from './auth.js'
import { overlay, btnCancel, btnCancel2, btnSave } from './dom.js'
import { lastResultIntent, resetConversation, continueSideAction } from './chat.js'
import { loadReminders } from './reminders.js'
import { _tourStep, _tourDone, showTourStep, removeTourUI } from './tour.js'

// ─── Confirm Modal ────────────────────────────────────────────────────────────
let _pendingExtracted = null
const SAVE_BTN_LABEL  = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Save Reminder`

export function showConfirmModal(extracted) {
  _pendingExtracted = extracted
  document.getElementById('field-title').value     = extracted.title    || ''
  document.getElementById('field-location').value  = extracted.location || ''
  document.getElementById('field-type').value      = extracted.type     || 'personal'
  document.getElementById('field-repeat').value    = extracted.repeat   || 'none'
  document.getElementById('field-datetime').value  = extracted.datetime
    ? extracted.datetime.slice(0, 16) : ''
  document.getElementById('field-duration').value   = extracted.duration_minutes ?? ''
  document.getElementById('field-pre-alert').value = extracted.pre_alert_minutes ?? ''
  document.getElementById('field-follow-up').value = extracted.follow_up_minutes ?? ''
  overlay.classList.add('show')

  // Tour step 3 — fires when modal opens after user recorded
  if (isDemo() && _tourStep === 2 && !_tourDone) {
    removeTourUI()
    setTimeout(() => showTourStep(3), 350)
  }
}

function closeModal() {
  overlay.classList.remove('show')
  // Only reset if creating was the actual point of this conversation. If this
  // modal was a detour (e.g. offering to create a replacement mid-update) and
  // the user declines it, the original conversation is still unresolved —
  // leave it open rather than wiping it out.
  if (lastResultIntent === 'create') {
    resetConversation()
  }
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
    duration_minutes:  document.getElementById('field-duration').value !== ''
                         ? parseInt(document.getElementById('field-duration').value) : null,
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
      await loadReminders()

      // Only reset if creating was the actual point of this conversation.
      // If it was a detour (e.g. creating a replacement mid-update), keep
      // the conversation open and let the agent resume the original task.
      if (lastResultIntent === 'create') {
        resetConversation()
      } else {
        setTimeout(() => continueSideAction(`Created "${title}" ✓.`), 800)
      }

      // Tour step 4 — fires after reminder saved and cards are rendered
      if (isDemo() && _tourStep === 3 && !_tourDone) {
        setTimeout(() => showTourStep(4), 500)
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