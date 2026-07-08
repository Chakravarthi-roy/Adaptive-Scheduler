"""
agent package — pipeline: input → router → prompt selection → reasoning/acting
loop → tools → memory (conversation history + DB).

main.py does `from agent import run_agent` — this file makes that keep
working exactly as before, so no other file needs to change.
"""

from .orchestrator import run_agent

__all__ = ["run_agent"]