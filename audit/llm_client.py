#!/usr/bin/env python3
"""
llm_client.py — swappable LLM backend for claim-support checking.

Backend selection is one env var (LLM_BACKEND, default "anthropic"). This is
the only file check_claims.py talks to for model calls — swapping to a local
model later (required before this touches unpublished manuscript text) means
adding a branch here, not touching the caller.

Env vars:
    LLM_BACKEND        "anthropic" (default) — only backend implemented so far
    ANTHROPIC_API_KEY   required for the anthropic backend
    CLAUDE_MODEL         defaults to "claude-sonnet-5"
"""

import os
import requests

BACKEND = os.environ.get("LLM_BACKEND", "anthropic")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class LLMError(Exception):
    pass


def _complete_anthropic(system: str, user: str, max_tokens: int) -> str:
    if not ANTHROPIC_API_KEY:
        raise LLMError(
            "ANTHROPIC_API_KEY is not set. Export it before running check_claims.py."
        )
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    r = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )


def complete(system: str, user: str, max_tokens: int = 500) -> dict:
    """Run one LLM call. Returns {"text", "model", "backend"} — the caller is
    responsible for logging this dict verbatim (see check_claims.py)."""
    if BACKEND == "anthropic":
        text = _complete_anthropic(system, user, max_tokens)
        return {"text": text, "model": ANTHROPIC_MODEL, "backend": "anthropic"}
    raise LLMError(f"Unknown LLM_BACKEND: {BACKEND!r}")
