import { loadReminders } from './reminders.js'
import { populateSettings } from './settings.js'

// ─── Navigation ───────────────────────────────────────────────────────────────
// Exported as a live `let` binding — reminders.js imports this directly rather
// than duplicating view state; ES modules keep such bindings live, so
// reminders.js always sees the current value without needing a getter.
export let currentView = 'reminders'

export function switchView(view) {
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