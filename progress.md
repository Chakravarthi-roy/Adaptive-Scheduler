# Progress Log — Adaptive Scheduler

Running changelog of every change made to this codebase across working sessions with Claude. Newest session at the top. Hand this file to a new chat to pick up where we left off without re-explaining everything.

**Note on dates/times:** entries are grouped by session date (the date the work happened), in the actual order changes were made within that session. Individual timestamps aren't tracked — just chronological order within each day.

---

## 2026-07-17 — Session 1

### Reviewed
- Full backend (`main.py`, `auth.py`, `database.py`, `agent.py`, `reminders.py`, `scheduler.py`, `notification.py`, `push.py`, `email_sender.py`) and frontend (`index.html`, `app.js`, `style.css`, `login.html`, `reset-password.html`, `manifest.json`, `sw.js`) against the README.
- Confirmed feature 9 ("converse with agent — upcoming") was actually already built in `agent.py`'s query workflow.
- Found real gaps: settings (custom time-words, timezone) were client-side only (`localStorage`), never synced to backend; `agent.py` read `user.timezone` from DB but that column didn't exist; vibration toggle was UI-only, not wired to real push notifications.

### Designed & built — conversational query workflow (gaps + history search)
- Discussed: gap-finding needs duration data; decided to capture `duration_minutes` at creation time (editable in the modal, like pre-alert/follow-up) rather than only asking retroactively.
- **Fixed a major bug**: `_run_loop` was returning the original input `messages` instead of the full conversation (`full_messages`) on every branch — this silently dropped the assistant's own tool calls and prior questions between turns, causing the agent to repeat clarifying questions and re-fetch data it already had. Fixed to return `full_messages[1:]` everywhere.
- Added `duration_minutes` column to `Reminder` model (`database.py`) — **requires a one-time manual migration on Supabase**: `ALTER TABLE reminders ADD COLUMN duration_minutes VARCHAR;`
- Added duration estimation logic to the create prompt; added a Duration field to the confirm modal (`index.html`, `app.js`), pre-filled by the agent, editable before saving.
- Added `find_schedule_gaps_tool` (computes real free windows in Python, 7am–6pm default window, merges busy intervals) and `search_reminders_tool` (general filter: title + relative date range + status) to the query workflow — LLM only picks tools/params, never does date arithmetic itself.
- Updated `reminders.py` to accept/return `duration_minutes`.

### Bug fix — search was doing exact-phrase matching
- User tested: "did I attend the wedding last month" against a reminder titled "go to the wedding" → failed, and the agent asked a leading confirmation question instead of admitting the search came up empty.
- Root cause: `ILIKE '%{query_text}%'` required the whole extracted phrase to literally appear in the title.
- Fixed: token-based OR matching — strips filler/verb words (attended, went, the, etc.) and matches on any remaining significant word.
- Also tightened the query prompt: forbidden from using `ask_user` as a substitute for reporting an empty search result.

### Architecture refactor — split `agent.py` into a package
- Discussed agent architecture principles (memory/planning/tools separation). Conclusion: tools and memory (conversation history + DB) were already properly separated; reasoning+acting are intentionally fused (ReAct-style, one LLM call decides both) rather than split into a separate planning call, since that would add latency with no real benefit at this app's scale.
- Split the old single `agent.py` into a package:
  - `agent/router.py` — intent classification (plain keyword matching, no LLM call)
  - `agent/context.py` — per-user timezone lookup
  - `agent/tools.py` — every DB-touching function, each now catches its own exceptions and returns `{"error": ...}` instead of raising
  - `agent/prompts.py` — all four workflow prompts + shared rules (`_SHARED`)
  - `agent/orchestrator.py` — the loop itself (LLM call → parse → dispatch), each step with its own error handling
  - `agent/__init__.py` — re-exports `run_agent` so `main.py`'s import didn't need to change
- **Old `agent.py` file was deleted** — must be removed from the actual repo too before deploying the new package (file + folder with the same name conflicts).

### Duration logic — fixed forcing a number onto everything
- Bug: create workflow was guessing a duration (30/60 min) for *every* task, including things with no real duration like "select a problem statement for a hackathon."
- Redesigned into 4 real buckets:
  1. Instant (casual/routine) → `0`
  2. Externally-timed events (exam, movie, flight) → ask once, e.g. "How long is the exam?"
  3. Self-paced sessions (reading, studying, working out) → ask once about the **planned session**, e.g. "How long do you want to read?" — NOT "how long does it take" (unanswerable for open-ended activities)
  4. Unbounded/decision tasks (choosing, deciding, picking) → never asked, never guessed, left `null`
- Pre-alert reinforced to default `0` unless there's something to actually prepare.
- Follow-up now keys off "is duration known" rather than reminder type — `duration + 10` when known, `0` when null.

### README
- Corrected grammar/typos, updated feature 9 from "(upcoming)" to implemented with a real description.
- Added proper markdown formatting: title, TOC, headers, bold/italic, code blocks, blockquotes.
- Full feature audit — flagged missing items (repeat reminders, full account system, timezone selector, multi-device push, PWA/installable) — user is adding these to the features list themselves.
- Added a full **"Now lets get technical!"** section: architecture split writeup, full prompt-flow walkthrough, tools layer, memory design (stateless server + DB long-term), how the agent handles follow-up questions, ending conversations properly, notifications/cron job reasoning (fact-checked: `cron-job.org` free 1-min intervals vs UptimeRobot's 5-min free limit vs Render Cron's $1/mo minimum), push notifications, error handling, brief auth mention.

### Password reset — discussed, not changed
- Confirmed link-based reset (already built) is more secure than OTP by default; recommended keeping it rather than rebuilding as OTP.
- Diagnosed why reset "always seems to work" even when untested: `/forgot-password` always returns `{"status": "ok"}` by design (prevents email enumeration) even if the email never actually sends when `GMAIL_USER`/`GMAIL_APP_PASSWORD` aren't set.
- Recommended: dedicated Gmail account (not personal), 2-Step Verification + App Password, set as Render env vars. **Not yet done by user.**

### Git issues fixed (two separate incidents)
1. `cannot lock ref 'refs/remotes/origin/main'` — resolved by deleting the stale loose ref (`Remove-Item .git\refs\remotes\origin\main`) and re-fetching.
2. `fatal: bad object refs/remotes/origin/main` — same fix, `Remove-Item` + `git fetch origin`.
- Discussed commit/deploy practice — user pushes often to test on Render; confirmed this is fine for solo dev as long as DB migrations are run *before* pushing dependent code (user already does this manually via Supabase SQL editor).

### Conversation UX — ending flow + opaque chat panel
- Built: after an `answer`-type response, agent watches for "thanks" → replies "You're welcome! Anything else?" → then "no" → replies and auto-closes the chat. Detected entirely client-side (no backend call needed for pleasantries).
- Added a persistent **"× close chat"** button for people who won't naturally say thanks — always visible during an active conversation.
- Made `.chat-bubbles` opaque once there's actual content (background/border/shadow), so reminder cards scrolling underneath no longer show through the gaps between bubbles. Also flipped `pointer-events` to `auto` when opaque, so it actually blocks taps on what's behind it, not just visually.

### Demo user cleanup — two bugs found and fixed
1. `_cleanup_old_demo_users` had a bug: if no admin account existed, demo users **with** a reminder were skipped entirely (`continue`), never deleted. Fixed to delete their reminders too when no admin exists, rather than getting stuck.
2. Real root cause of stale demo data: cleanup was **lazy** — only ran when someone hit `/auth/demo` to start a *new* demo session. If nobody did, old demo data (including the user's own stuck browser session) never got purged. Fixed by wiring `run_demo_cleanup()` into the existing `/cron/check-reminders` endpoint (already pinged every minute by cron-job.org) — cleanup is now fully automatic and time-based. TTL set to 12 hours (was 24).

### Create-workflow bug — "tomorrow" with no time skipped straight to duration
- User's friend: "I have an exam tomorrow remind me" → agent asked about duration first instead of asking what time tomorrow.
- Root cause: no rule distinguished "a bare day/date with no time-of-day" from "fully specified time" — the model silently guessed a default time instead of treating it as missing, and there was no stated priority between "time missing" and "duration missing."
- Fixed: added an explicit **PRIORITY GATE** to the create prompt — title and a full date+time must both be resolved before duration (or anything else) is even considered. A bare day like "tomorrow" now explicitly counts as missing time and triggers "What time tomorrow?" instead of a silent guess.

### Prompt audit (full read-through against everything discussed)
- Confirmed correct: duration buckets, ask-once rules, pre-alert/follow-up defaults, priority gate, gap window + stated range, chunk-of-2 duration asking during gaps, no-guessing-on-empty-search, tighter search keywords, tool error surfacing.
- Found one real gap: `UPDATE_PROMPT` had zero duration-handling guidance despite `duration_minutes` being in its output schema.

### Cascade/ripple update system — designed in detail, NOT YET IMPLEMENTED
Extensive design discussion for: when updating a reminder's duration causes it to overlap the next reminder, should the next one auto-shift? Agreed mechanism (not yet built):
- Trigger: only if new duration's end time actually overlaps the next reminder.
- Type-based eligibility: `important` reminders can be moved with a graduated safety check (≥20min gap after move = fine; 10–20min = soft flag; <10min = explicit "still want to make this change?"). `casual`/`personal` reminders (lunch, calls, etc.) never move silently — any collision always asks first.
- Ripple: if moving one reminder creates a new collision with the *next* one, that's a fresh decision point too (not automatic) — and if more than 3 reminders would need to move, ask once upfront rather than per-step.
- Bulk move with pinned exceptions: "move everything 2 hours after this" should let the user name specific reminders to keep fixed ("this one and that one should stay on time") and recompute the shift around those — flagged as having real unsolved math (what happens when a pinned reminder leaves too little room for something squeezed before it).
- **This entire system is designed but not coded yet** — next session's likely starting point if picked back up.

### Phrasing rule — implemented immediately (pulled out of the cascade discussion)
- Added to `_SHARED` (applies to all 4 prompts): talk about reminders like describing someone's plans in conversation, never like a database readout — "u wanted to have lunch at 2PM" not "u have a lunch reminder at 2PM." When asking about a change, name the specific thing changing ("still want to change the lunch timing?") not a vague "still want to make changes?" Tone stays the same regardless of type — only *caution about touching it* should differ.

### UPDATE_PROMPT — full fix
- Added missing schema fields: `type`, `repeat`, `action_label` (were completely absent before).
- No-match handling: "There's no such reminder — did u mean one of these?" instead of guessing an ID.
- Recurring reminders: explicitly asks "just for today, or change the everyday schedule?" instead of assuming scope.
- Follow-up recalculates (`duration + 10`) when duration changes instead of going stale.
- Added a lightweight collision mention (not the full cascade system — just a basic "this overlaps with X" heads-up).
- **Cross-workflow side-actions**: `create_reminder` and `delete_reminder` are now valid mid-conversation moves within the update workflow (e.g. "no match → create it instead", "collision found → delete the other one"), while staying anchored to the original update task.

### Cross-workflow conversation continuity — backend + frontend
- `orchestrator.py`: `run_agent` now attaches the whole-conversation `intent` (classified once, from the first message) to every result returned.
- `app.js`: refactored response handling into `processAgentResult()` (shared by the normal flow and a new `continueSideAction()` helper). The modal's save/cancel, and the `updated`/`deleted` result branches, now compare `lastResultIntent` (what the conversation was fundamentally about) against what just happened — if they match, it's the real goal completing and resets as before; if they don't match, it was a detour, so the conversation stays open and automatically nudges the agent to resume the original task instead of ending.

---

## Files touched this session
`agent.py` (deleted, replaced by `agent/` package) · `agent/router.py` · `agent/context.py` · `agent/tools.py` · `agent/prompts.py` · `agent/orchestrator.py` · `agent/__init__.py` · `database.py` · `reminders.py` · `main.py` · `auth.py` · `app.js` (deleted, replaced by `js/` package — see Session 4) · `js/config.js` · `js/dom.js` · `js/auth.js` · `js/push.js` · `js/settings.js` · `js/views.js` · `js/reminders.js` · `js/chat.js` · `js/modal.js` · `js/tour.js` · `js/main.js` · `index.html` · `login.html` · `style.css` · `sw.js` · `README.md`

## Manual steps required (not automatable from here)
- [ ] Run `ALTER TABLE reminders ADD COLUMN duration_minutes VARCHAR;` on Supabase (if not already done)
- [ ] Delete old `agent.py` from the actual repo before adding the new `agent/` folder
- [ ] **Delete old `app.js` from the actual repo before adding the new `js/` folder** — replace, don't just add alongside
- [ ] Set up a dedicated Gmail account + App Password for password-reset emails, add `GMAIL_USER`/`GMAIL_APP_PASSWORD` to Render env vars
- [ ] Test the `js/` module refactor for real in a browser once deployed — it was verified via static analysis (syntax + import/export cross-checks) since this environment can't run a browser, so an actual click-through pass is worth doing before trusting it fully

## Known open items (discussed but not built)
- Full cascade/ripple system for update-triggered reminder shifts (designed in detail above, not coded)
- Bulk move with pinned exceptions — math not fully worked out yet
- Vibration setting still UI-only, not synced to real push notifications
- Timezone setting still `localStorage`-only, not synced to the `User.timezone` DB column `agent.py` actually reads
- Snooze button plumbing exists (endpoint + service worker handler) but isn't exposed in the notification UI yet

See `ISSUES.md` for the full tracked issue list with status/priority.

---

## 2026-07-17 — Session 2

### Bug fix — pre-alert/follow-up "0" was being silently discarded
- User reported pre-alerts firing even though the modal clearly showed `0` for both pre-alert and follow-up.
- Root cause found in `reminders.py`: `pre_alert_minutes=data.get("pre_alert_minutes") if data.get("pre_alert_minutes") else None` — `0` is falsy in Python, so an explicit `0` was being silently replaced with `None`. `scheduler.py` then treated `None` as "not set" and fell back to the type-based default (e.g. 20 min for `important`) instead of respecting the explicit zero.
- This is the exact same bug class already fixed for `duration_minutes` earlier — `pre_alert_minutes`/`follow_up_minutes` were legacy code that never got the same fix. Now fixed to check `not in (None, "")` instead of a truthy check.

### Regression fix — create workflow was asking for time even when time was given
- The PRIORITY GATE added last session (to fix "tomorrow" skipping straight to duration) overcorrected — its repeated negative framing ("must ask," "never guess," "stop there") biased the model into asking about time even when a time was clearly stated.
- Rewrote `TIME RULES` to lead with an explicit **positive checklist** of what already counts as specified (explicit clock time, mapped words, relative expressions, inferable context) before any negative framing — should stop the over-triggering while keeping the original "tomorrow" fix intact.

### Backlog
- Location tracking — new feature, not yet designed. Flagged for a future dedicated design session (similar depth to the duration/gap discussion).

### Investigating
- "Missing notif looks odd" — reported but not enough detail yet to diagnose. Waiting on specifics (wording? icon? timing?) before touching any code.

---

## 2026-07-17 — Session 3

### Bug fix — notification action buttons silently failed, causing false "missed" markings
- Follow-up on "missing notif looks odd": user clarified they clicked the notification button for both pre-alert AND on-time notifications, but the reminder still ended up marked missed.
- **Root cause found**: `sw.js`'s notification-click handler fired `fetch('/reminders/{id}/done')` and `.../snooze` with no `Authorization` header at all — service workers can't read `localStorage`, where the token lives. The backend correctly returned 401, but `fetch()` only rejects on network failures, never on HTTP error statuses — so the `.catch()` never fired. The click looked successful; the server never received a valid request; the reminder was later, correctly from the scheduler's own perspective, marked missed since `done` genuinely stayed `False`.
- **Fixed**: token now mirrors into IndexedDB (readable from both the page and the service worker) at every point it's set (`login.html`'s login/signup/demo) and cleared on logout/401 (`app.js`). Already-logged-in sessions get synced on next page load too. `sw.js` gained an `authedFetch()` helper that reads the token from IndexedDB and attaches it before firing, plus logs any non-2xx response so a similarly silent failure can't hide again. Cache version bumped `v1` → `v2` so the new service worker installs cleanly.

---

## 2026-07-17 — Session 4

### Frontend refactor — split `app.js` into a `js/` module package
- Same idea as the earlier `agent/` package split, applied to the frontend. Old monolithic `app.js` (1178 lines) split into 11 files under `js/`, grouped strictly by domain:
  - `config.js` — API_BASE, VAPID key
  - `dom.js` — every `getElementById` reference, grabbed once and shared
  - `auth.js` — token/session management, IndexedDB mirror for the service worker
  - `push.js` — push notification subscription setup
  - `settings.js` — settings panel, time-word preferences, clock, agent-context builder
  - `views.js` — nav/view switching
  - `reminders.js` — fetch/render/filter/mark-done for the reminder list
  - `chat.js` — recording, bubbles, the full agent conversation flow
  - `modal.js` — the confirm-reminder modal
  - `tour.js` — the demo walkthrough
  - `main.js` — entry point, wires everything, bridges the handful of functions HTML's inline `onclick=` needs onto `window`
- Real ES modules (`import`/`export`), no build tool — browsers support this natively.
- **`index.html`** updated: `<script src="app.js">` → `<script type="module" src="js/main.js">`. Old `app.js` is now dead, removed.
- **One deliberate circular import** (`chat.js` ↔ `modal.js`) — verified safe since neither module uses the other's import at the top level, only inside functions called later at event time. Confirmed via an actual static cross-reference check (every `import` matched against a real `export`), not just by eye.
- **Auth guard moved out of the module system** — originally planned to keep it as the first line of `main.js`, but caught a real issue: ES module imports are hoisted and fully evaluated before any importing file's own top-level code runs, so a guard inside `main.js` would've actually executed AFTER every other module's setup code (DOM queries, event listeners), defeating the point. Moved to a plain inline `<script>` in `index.html`, placed BEFORE the module script tag, so it's guaranteed to run first.
- **`sw.js` stays at the project root**, not inside `js/` — a service worker's scope is determined by its own file location; it has to sit at root to control the whole site (and `push.js`'s `register('./sw.js')` call already expects it there).
- `sw.js`'s offline shell cache list updated to reference all the new module files instead of the old single `app.js`. Cache version bumped `v2` → `v3`.
- **Caveat noted**: ES modules require being served over `http(s)://` — won't work opening `index.html` directly via `file://` due to CORS restrictions on module scripts. Not an issue on Render, only relevant for local testing without a dev server.