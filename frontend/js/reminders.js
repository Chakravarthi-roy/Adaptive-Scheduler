import { API_BASE } from './config.js'
import { getToken, handle401, isDemo } from './auth.js'
import { currentView } from './views.js'

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

export async function loadReminders() {
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

export function renderReminders(allReminders) {
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

export async function markDone(id) {
  await fetch(`${API_BASE}/reminders/${id}/done`, {
    method: 'PATCH',
    headers: { 'Authorization': `Bearer ${getToken()}` }
  })
  loadReminders()
}