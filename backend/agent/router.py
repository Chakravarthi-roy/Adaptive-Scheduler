"""
router.py — intent routing

Plain keyword matching, no LLM call. This step costs microseconds — comparing
a handful of substrings against one string, entirely in-process. It does NOT
meaningfully affect request latency; the real cost in this pipeline is the
LLM calls further downstream. Kept rule-based specifically to avoid paying
for an extra network round-trip just to decide which prompt to use.
"""

_QUERY_SIGNALS  = [
    "do i have", "what do i have", "show me", "list", "check",
    "any gaps", "free time", "did i", "have i", "when is", "when was",
    "what time", "how many", "any reminders"
]
_DELETE_SIGNALS = [
    "delete", "remove", "cancel", "forget", "drop", "clear",
    "stop reminding", "dismiss", "get rid of"
]
_UPDATE_SIGNALS = [
    "update", "change", "move", "reschedule", "edit", "modify",
    "shift", "postpone", "delay", "bring forward", "earlier", "later",
    "rename", "push to", "push it"
]


def classify_intent(text: str) -> str:
    """Returns one of: create, update, delete, query. Falls back to 'create',
    the most common intent, when nothing matches."""
    t = text.lower()
    if any(s in t for s in _QUERY_SIGNALS):  return "query"
    if any(s in t for s in _DELETE_SIGNALS): return "delete"
    if any(s in t for s in _UPDATE_SIGNALS): return "update"
    return "create"