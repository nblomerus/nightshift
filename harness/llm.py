"""LLM clients for seats. A client is any callable ``llm(prompt, system=None, tier=None) -> str``.
``tier`` is ``"reasoning"`` or ``"utility"`` (see the rigspec); map tiers to models here, never in seat code."""

from __future__ import annotations

import json
import urllib.request


class Reply(str):
    """The reply text, as seat code sees it, carrying the model's separate reasoning (if the endpoint returns one)
    for the call record only."""

    def __new__(cls, text, reasoning=None):
        obj = super().__new__(cls, text)
        obj.reasoning = reasoning
        return obj


def openai_compatible_llm(
    base_url: str,
    reasoning_model: str,
    utility_model: str,
    api_key: str = "none",
    max_tokens: int = 16000,
    timeout: int = 600,
):
    """Any OpenAI-compatible chat endpoint: a local vLLM / SGLang / Ollama server or a hosted API.
    Reasoning models spend tokens thinking, so keep ``max_tokens`` generous: 4k was too small, and at 8k DeepSeek's
    reasoner sometimes spent it all thinking and returned an empty reply."""

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
        msg = json.load(urllib.request.urlopen(req, timeout=timeout))["choices"][0]["message"]
        return Reply(msg["content"], reasoning=msg.get("reasoning_content"))

    return llm


def recording_llm(llm, path):
    """Wrap an LLM client so every call is appended to `path` (JSON lines) as a `start` record before the call
    and an `end` record after it, with the seat (from the persona), tier, prompt, reply and timings. The lab floor
    reads this to show who is thinking and what each seat was asked and said. The record is written, never read,
    by the lab: it cannot influence a decision."""
    import itertools
    import os
    import re
    import time

    counter = itertools.count(1)

    def write(rec):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def llm_rec(prompt, system=None, tier=None):
        call = next(counter)
        m = re.match(r"You are (\S+?),", system or "")
        seat = m.group(1) if m else None
        t0 = time.time()
        write(dict(event="start", call=call, seat=seat, tier=tier, t=t0))
        try:
            reply = llm(prompt, system=system, tier=tier)
        except Exception as e:
            write(dict(event="end", call=call, seat=seat, tier=tier, t=time.time(), s=round(time.time() - t0, 2),
                       system=system, prompt=prompt, reply=None, error=f"{type(e).__name__}: {e}"))  # fmt: skip
            raise
        write(dict(event="end", call=call, seat=seat, tier=tier, t=time.time(), s=round(time.time() - t0, 2),
                   system=system, prompt=prompt, reply=str(reply), reasoning=getattr(reply, "reasoning", None),
                   error=None))  # fmt: skip
        return reply

    return llm_rec
