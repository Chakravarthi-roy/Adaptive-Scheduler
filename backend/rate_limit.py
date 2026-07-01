from slowapi import Limiter
from slowapi.util import get_remote_address

# Single shared limiter instance — imported by main.py, reminders.py, push.py
# so rate limits work consistently across all routers without circular imports.
limiter = Limiter(key_func=get_remote_address)