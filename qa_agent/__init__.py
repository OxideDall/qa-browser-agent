"""QA agent — LLM-driven Playwright + uiautomator2 testing.

Public API (used by mcp_server.py and external callers):
    run_task          — browser task (Playwright)
    run_android_task  — Android task (uiautomator2)
    setup_metamask    — one-shot MM wallet bootstrap
    METAMASK_EXT, PROFILE_DIR, MODEL (paths/constants)

LLM provider auth: env-only — see qa_agent.providers.
"""

from .agent import run_android_task, run_macro_task, run_tagged_task, run_task
from .config import METAMASK_EXT, MODEL, PROFILE_DIR
from .metamask import setup_metamask

__all__ = [
    "run_task",
    "run_android_task",
    "run_tagged_task",
    "run_macro_task",
    "setup_metamask",
    "METAMASK_EXT",
    "PROFILE_DIR",
    "MODEL",
]
