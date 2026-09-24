"""
Optional external LLM adapter.

NIECP-AI works fully without an external LLM: the deterministic rule engine and
the local retrieval corpus answer everything. When an operator configures
`NIECP_LLM_PROVIDER` + `NIECP_LLM_API_KEY`, generation calls are routed through
this adapter with a strict system prompt that:

  * forbids inventing government facts, thresholds, statuses or references;
  * requires every regulatory statement to be grounded in the retrieved chunks;
  * instructs the model to say "I could not verify this" when grounding is weak;
  * keeps the deterministic rule-engine verdicts authoritative — the LLM may
    explain them but never change them.

Failures degrade gracefully: a timeout or error returns `available=False` and
the caller falls back to the local composer, telling the user which path was
used. We never claim an external model was consulted when it was not.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger("niecp.llm")

SYSTEM_PROMPT = """You are the NIECP-AI assistant: an industrial approval and compliance navigator for India.
Hard rules you must never break:
1. Never invent government requirements, thresholds, fees, application numbers, statuses, officer names or decisions.
2. Base regulatory statements ONLY on the RETRIEVED CONTEXT provided to you. If the context does not support an answer, say: "I could not verify this from the available official sources."
3. Deterministic rule-engine results marked RULE VERDICT are authoritative. Explain them; never contradict or re-derive them.
4. Never promise or guarantee approval, and never imply NIECP-AI is a government authority.
5. Submissions to governments happen only on official portals by the user (or via a verified integration the operator has provisioned). Encourage the user to confirm on the official portal.
6. Be concise, practical and structured. Use the requested response format when given.
7. Reply in the user's language when asked (English, Tamil or Hindi are supported)."""

JSON_RE = re.compile(r"\{.*\}", re.S)


@dataclass
class LLMResponse:
    text: str
    available: bool
    provider: str
    model: str | None
    error: str | None = None
    used_fallback: bool = False


def llm_configured() -> bool:
    return bool(settings.llm_provider and settings.llm_provider != "none" and settings.llm_api_key)


def llm_status() -> dict[str, Any]:
    return {
        "configured": llm_configured(),
        "provider": settings.llm_provider if llm_configured() else "none",
        "model": settings.llm_model if llm_configured() else None,
        "note": (
            "An external LLM is configured and may be used to phrase answers; regulatory verdicts always come "
            "from the deterministic rule engine."
            if llm_configured()
            else "No external LLM is configured. The assistant answers from the local rule engine and the "
            "curated knowledge corpus, and says so. AI assistance features that require generation are served "
            "locally; nothing is simulated."
        ),
    }


def generate(
    user_message: str,
    *,
    context_chunks: list[dict[str, Any]] | None = None,
    project_context: dict[str, Any] | None = None,
    rule_verdicts: list[dict[str, Any]] | None = None,
    response_format_hint: str | None = None,
    max_tokens: int = 900,
) -> LLMResponse:
    if not llm_configured():
        return LLMResponse(text="", available=False, provider="none", model=None, error="not_configured", used_fallback=True)

    parts = [SYSTEM_PROMPT]
    if project_context:
        parts.append("PROJECT CONTEXT (user-provided data):\n" + json.dumps(project_context, ensure_ascii=False, default=str)[:4000])
    if rule_verdicts:
        parts.append("RULE VERDICTS (authoritative, deterministic):\n" + json.dumps(rule_verdicts, ensure_ascii=False, default=str)[:4000])
    if context_chunks:
        rendered = []
        for i, c in enumerate(context_chunks, 1):
            rendered.append(
                f"[{i}] {c.get('title')} — {c.get('publisher') or ''} ({c.get('verification_status')})\n{c.get('excerpt') or c.get('text','')[:700]}"
            )
        parts.append("RETRIEVED CONTEXT (cite as [n] when used):\n" + "\n\n".join(rendered)[:8000])
    if response_format_hint:
        parts.append(f"RESPONSE FORMAT:\n{response_format_hint}")

    try:
        headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": settings.llm_model,
            "messages": [{"role": "system", "content": "\n\n".join(parts)}, {"role": "user", "content": user_message}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            resp = client.post(f"{settings.llm_base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
        if resp.status_code != 200:
            return LLMResponse(text="", available=False, provider=settings.llm_provider, model=settings.llm_model,
                               error=f"HTTP {resp.status_code}", used_fallback=True)
        data = resp.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return LLMResponse(text=text.strip(), available=bool(text), provider=settings.llm_provider, model=settings.llm_model)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("LLM call failed: %s", exc)
        return LLMResponse(text="", available=False, provider=settings.llm_provider, model=settings.llm_model,
                           error=str(exc), used_fallback=True)
