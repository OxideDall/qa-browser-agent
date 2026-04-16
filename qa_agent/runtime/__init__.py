"""Pure helpers for the agent loop.

Extracted from agent.py as Phase 1 of the FSM refactor (bench/fsm_design.md).
Everything here is a pure function or a constant — no Playwright, no LLM,
no I/O. Safe to import standalone in tests and bench asserts.
"""
