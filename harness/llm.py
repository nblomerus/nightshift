"""LLM clients for seats. A client is any callable ``llm(prompt, system=None, tier=None) -> str``.
``tier`` is ``"reasoning"`` or ``"utility"`` (see the rigspec); map tiers to models here, never in seat code."""

from __future__ import annotations

import json
import urllib.request


def openai_compatible_llm(
    base_url: str,
    reasoning_model: str,
    utility_model: str,
    api_key: str = "none",
    max_tokens: int = 8000,
    timeout: int = 600,
):
    """Any OpenAI-compatible chat endpoint: a local vLLM / SGLang / Ollama server or a hosted API.
    Reasoning models spend tokens thinking, so keep ``max_tokens`` generous (4k was too small in practice)."""

    def llm(prompt, system=None, tier=None):
        body = dict(
            model=reasoning_model if tier == "reasoning" else utility_model,
            max_tokens=max_tokens,
            messages=([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}],
        )
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        return json.load(urllib.request.urlopen(req, timeout=timeout))["choices"][0]["message"]["content"]

    return llm
