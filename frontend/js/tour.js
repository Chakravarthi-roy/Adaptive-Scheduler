import { isDemo } from './auth.js'
import { showToast } from './chat.js'

// ─── DEMO TOUR ────────────────────────────────────────────────────────────────
export let _tourStep = 0
export let _tourDone = localStorage.getItem('demo_tour_done') === 'true'
let _tourEl = null
let _spotEl = null

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

export function setupDemoMode() {
  if (!isDemo()) return
  _injectDemoStyles()

  // Start tour if not yet completed
  if (!_tourDone) {
    setTimeout(() => showTourStep(1), 700)
  }
}

export function showTourStep(id) {
  removeTourUI()
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
  if (step.isAction)         nextAction = `onclick="_pauseForAction()"`
  else if (step.waitForSave) nextAction = `onclick="_waitForSave()"`
  else if (step.nextHref)    nextAction = `onclick="endTour();window.location.href='${step.nextHref}'"`
  else                       nextAction = `onclick="_nextTourStep()"`

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

export function _nextTourStep() {
  const nextId = _tourStep + 1
  const next   = TOUR_STEPS.find(s => s.id === nextId)
  if (!next)            { endTour(); return }
  // Auto-trigger steps fire from events — skip when navigating manually
  if (next.autoTrigger) { _tourStep = nextId; _nextTourStep(); return }
  showTourStep(nextId)
}

export function _pauseForAction() {
  // User tapped "Try it now!" — dismiss overlay so they can tap mic
  // _tourStep stays at 2; step 3 fires when the confirm modal opens
  removeTourUI()
  showToast('Tap the mic and say a reminder!')
}

export function _waitForSave() {
  // User tapped "Got it" on the review step — just close the panel
  // _tourStep stays at 3; step 4 fires from btnSave after reminder is saved
  removeTourUI()
}

export function endTour() {
  removeTourUI()
  _tourDone = true
  _tourStep = 0
  localStorage.setItem('demo_tour_done', 'true')
}

export function removeTourUI() {
  if (_tourEl) { _tourEl.remove(); _tourEl = null }
  if (_spotEl) { _spotEl.remove(); _spotEl = null }
}