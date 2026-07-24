# Issues — Adaptive Scheduler

Tracked separately from `PROGRESS.md` (which logs what was *done*) — this is what still *needs* doing, plus a record of what's already been fixed for reference. Update status as things move.

**Status key:** 🔴 Open &nbsp;·&nbsp; 🟡 Partial / in progress &nbsp;·&nbsp; 🟢 Fixed &nbsp;·&nbsp; ⚪ Decided not to build (documented reasoning)

---

## Open Issues

### 🔴 #1 — No cascade/ripple system for update-triggered collisions
When a reminder's duration is updated and it now overlaps the next reminder, nothing shifts automatically and there's no offer to shift it — the basic collision mention (`UPDATE_PROMPT`) just flags the overlap in the confirmation text. The full designed system (type-based eligibility, graduated 20/10-min thresholds, ripple cap, bulk-move-with-pinned-exceptions) is written up in `PROGRESS.md` under "Cascade/ripple update system" but not implemented.
**Priority:** whenever the app is used for a genuinely packed schedule, this becomes the most noticeable gap.

### 🔴 #2 — Vibration setting is UI-only
The Settings toggle only triggers `navigator.vibrate()` locally when tapped in the settings panel itself — it's never synced to the backend, so real push notifications always use the same fixed `sound`/`vibrate` logic in `notification.py` regardless of what the user set. Toggling it does nothing to actual reminder notifications.
**Fix needed:** add a `User.vibration_enabled` (or similar) DB column, sync from `app.js`'s `toggleVibration()`, read it in `notification.py`/`send_notification`.

### 🔴 #3 — Timezone setting not synced to backend
Settings panel lets the user pick a timezone (IST/EST/PST/etc.), but it's stored in `localStorage` only. `agent.py`/`context.py`'s `get_user_tz()` reads from `User.timezone` in the DB — a column that's either never populated, or populated by nothing the frontend currently writes to. This means the "current time" the agent reasons about and the timezone shown in Settings can silently disagree.
**Fix needed:** an endpoint to save timezone to the `User` row when changed in Settings, replacing/supplementing the `localStorage`-only approach.

### 🔴 #4 — Snooze not exposed in the notification UI
`POST /reminders/{id}/snooze` exists, and `sw.js` has a full `notificationclick` handler for a `snooze` action — but no notification currently includes a snooze button (`scheduler.py`'s notification payloads only ever set `action`/`action_label` for "done"-style actions). The plumbing is real but dead code until it's wired into an actual button.

### 🔴 #5 — Password reset emails not yet configured
`/forgot-password` always returns `{"status": "ok"}` (intentional, prevents email enumeration) even when `GMAIL_USER`/`GMAIL_APP_PASSWORD` env vars aren't set — so it *looks* like it's working from the frontend even if no email is actually sent. Needs a dedicated Gmail account + App Password set up and added to Render's env vars before this is actually functional. See `PROGRESS.md` for the reasoning on why link-based reset (not OTP) was kept.

### 🔴 #6 — `search_reminders`'s `relative_range` only covers fixed labels
Only recognizes: `today, yesterday, this_week, last_week, this_month, last_month, all`. Something like "last 3 days" or a custom date range has nothing to map onto, so the LLM will likely guess wrong or fall back to `all`. Would need a `start_date`/`end_date` pair added as an alternative to `relative_range` in `tools.py` + `QUERY_PROMPT`.

### 🔴 #7 — Bulk move with pinned exceptions — math not resolved
Part of the cascade design (#1): "move everything 2 hours after this, except these two" needs to recompute shifts around pinned reminders. Open question: if a pinned reminder in the middle leaves too little room for something squeezed before it, does the agent flag that specifically, or just do its best and report the result? Needs a decision before this can be built.

### 🔴 #8 — Location tracking (backlog, not yet designed)
User wants to add location tracking as a feature. Not scoped yet — open questions: geofenced "remind me when I arrive at X" vs. just displaying location on a map vs. something else. Needs its own dedicated design discussion before any code, same depth as the duration/gap discussions.

### 🔴 #10 — `app.js` → `js/` module refactor needs a real browser test pass
The split into `js/*.js` modules (see `PROGRESS.md` Session 4) was verified via static analysis only — every import/export cross-referenced programmatically, syntax-checked, circular import reasoned through carefully — but this environment can't run an actual browser, so it hasn't been click-tested end to end. Low risk given the verification done, but should be confirmed for real (recording → modal → save, settings panel, demo tour, view switching) before fully trusting it in production.

---

## Fixed Issues (for reference)

### 🟢 Notification action buttons silently failed to mark reminders done (was #9, "missing notif looks odd")
**Root cause:** `sw.js`'s notification-click handler sent `fetch()` requests to `/reminders/{id}/done` and `/reminders/{id}/snooze` with no `Authorization` header — service workers can't read `localStorage`, where the token lives. The backend correctly returned 401, but `fetch()` doesn't reject on HTTP error statuses, only network failures — so the failure was completely silent. Clicking the button looked like it worked; the server never got a valid request; the reminder correctly (from the scheduler's perspective) got marked missed an hour later since `done` genuinely never became `True`.
**Fixed:** token now also mirrors into IndexedDB (readable from a service worker, unlike localStorage) at every login/signup/demo point, cleared on logout, synced for already-logged-in sessions on next load. `sw.js` now reads it and attaches a real `Authorization` header via a new `authedFetch()` helper, which also logs any non-2xx response so a failure like this can't go invisible again.

### 🟢 Pre-alert/follow-up "0" was silently discarded, causing unwanted default firing
**Root cause:** `reminders.py` used `if data.get("pre_alert_minutes") else None` — falsy-zero bug, `0` was treated the same as "not provided" and replaced with `None`, which then fell back to the type-based default in `scheduler.py` (e.g. 20 min for `important`) instead of respecting the explicit `0`.
**Fixed:** changed to `not in (None, "")` check — same fix already applied to `duration_minutes` earlier, this was leftover legacy code that hadn't gotten it yet.

### 🟢 Create workflow started asking for time even when time WAS given
**Root cause:** the PRIORITY GATE fix (for the "tomorrow" bug) overcorrected — repeated negative framing ("must ask," "never guess") biased the model into over-triggering the ask-for-time branch.
**Fixed:** rewrote `TIME RULES` to lead with an explicit positive checklist of what already counts as specified, before any negative framing.

### 🟢 Repeated clarifying questions / agent "forgetting" mid-conversation
**Root cause:** `_run_loop` returned the original input `messages` instead of `full_messages` on every branch, silently dropping the assistant's own prior tool calls and questions between turns.
**Fixed:** all return branches now carry `full_messages[1:]`.

### 🟢 Search only matched exact phrases
**Root cause:** `ILIKE '%{query_text}%'` required the LLM's entire extracted phrase to literally appear in the title (e.g. "attended the wedding" didn't match "go to the wedding").
**Fixed:** token-based OR matching in `search_reminders_tool`, filler words stripped.

### 🟢 Agent asked a leading question instead of admitting a search came up empty
**Fixed:** `QUERY_PROMPT` now explicitly forbids using `ask_user` as a substitute for reporting an empty result.

### 🟢 Duration was force-guessed onto every reminder, including undurationable tasks
**Fixed:** rebuilt into 4 buckets (instant / externally-timed / self-paced / unbounded) — see `PROGRESS.md` for full detail.

### 🟢 Self-paced duration questions were unanswerable ("how long does reading a book take?")
**Fixed:** self-paced activities now ask about the *planned session* ("how long do you want to read?"), not the activity's supposed length.

### 🟢 "Tomorrow" with no time-of-day skipped straight to asking about duration
**Root cause:** no rule distinguished "date only" from "fully specified time," and no priority order existed between missing time vs. missing duration.
**Fixed:** added an explicit PRIORITY GATE — title + full time must resolve before duration is even considered.

### 🟢 Demo users with a reminder were never deleted if no admin account existed
**Root cause:** `_cleanup_old_demo_users` had a `continue` that skipped deletion entirely in that case.
**Fixed:** now deletes their reminders too and proceeds with deletion regardless of whether an admin exists.

### 🟢 Demo cleanup only ran when someone started a NEW demo session
**Root cause:** cleanup was lazy, triggered only inside `/auth/demo`.
**Fixed:** wired into the existing every-minute `/cron/check-reminders` endpoint — fully automatic now. TTL lowered 24h → 12h.

### 🟢 Chat conversation never had a way to close after a query answer
**Fixed:** client-side thanks/no detection + explicit "× close chat" button.

### 🟢 Chat bubbles were visually transparent, reminders showed through the gaps
**Fixed:** `.chat-bubbles.active` now has a real opaque background + `pointer-events: auto` so it also blocks taps on what's behind it.

### 🟢 `UPDATE_PROMPT` was missing `type`/`repeat`/`action_label` from its output schema
**Fixed:** added to the schema; also added no-match handling, recurring-reminder scope question, and follow-up recalculation on duration change.

### 🟢 Modal save/cancel always ended the conversation, even mid-detour
**Root cause:** no way to tell "the conversation's actual goal just completed" apart from "a side-action (e.g. creating something while updating) just happened."
**Fixed:** server now exposes whole-conversation `intent`; frontend compares it against what just happened to decide reset-vs-continue.

---

## Decided Not To Build (documented reasoning, not oversights)

### ⚪ OTP-based password reset
Considered, decided against — the existing 32-byte token link is already effectively unguessable, and OTP would actually be *less* secure without extra work (rate limiting, short expiry) most implementations skip. See `PROGRESS.md`.

### ⚪ Separate LLM call for intent classification
Considered, decided against — plain keyword matching costs microseconds; a dedicated classification LLM call would add a full network round-trip for no real accuracy benefit at this app's scale.

### ⚪ Full upfront multi-step planning (vs. ReAct one-step-at-a-time)
Considered as part of the architecture discussion — reasoning+acting are intentionally fused into one LLM call per step rather than split into a separate planning stage, since the workflows here are short (≤8 steps) and cheap to course-correct, unlike long-horizon exploratory agent tasks where upfront planning earns its cost.