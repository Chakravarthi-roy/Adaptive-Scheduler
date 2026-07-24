// ─── Elements ─────────────────────────────────────────────────────────────────
// Grabbed once here so every module imports the same references instead of
// re-querying the DOM (or worse, drifting out of sync with each other).
export const micBtn       = document.getElementById('mic-btn')
export const typeBtn      = document.getElementById('type-btn')
export const typeArea     = document.getElementById('type-area')
export const typeInput    = document.getElementById('type-input')
export const typeSend     = document.getElementById('type-send')
export const chatBubbles  = document.getElementById('chat-bubbles')
export const chatCloseBtn = document.getElementById('chat-close-btn')
export const overlay      = document.getElementById('overlay')
export const btnCancel    = document.getElementById('btn-cancel')
export const btnCancel2   = document.getElementById('btn-cancel-2')
export const btnSave      = document.getElementById('btn-save')
export const micToast     = document.getElementById('mic-toast')