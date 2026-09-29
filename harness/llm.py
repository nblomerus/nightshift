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
    stream: bool = True,
):
    """Any OpenAI-compatible chat endpoint: a local vLLM / SGLang / Ollama server or a hosted API.
    Reasoning models spend tokens thinking, so keep ``max_tokens`` generous: 4k was too small, and at 8k DeepSeek's
    reasoner sometimes spent it all thinking and returned an empty reply.

    With ``stream`` the reply arrives as server-sent chunks; ``on_progress(reasoning_so_far, content_so_far)`` is called
    as they arrive, so the lab floor can show a seat's thinking while the call is still running."""

    def llm(prompt, system=None, tier=None, on_progress=None):
        body = dict(
            model=reasoning_model if tier == "reasoning" else utility_model,
            max_tokens=max_tokens,
            messages=([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}],
            stream=stream,
        )
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not stream:
                msg = json.load(resp)["choices"][0]["message"]
                return Reply(msg["content"], reasoning=msg.get("reasoning_content"))
            return Reply(*read_stream(resp, on_progress))

    return llm


def read_stream(lines, on_progress=None):
    """(content, reasoning) from an OpenAI-style stream of `data: {...}` lines, reporting progress as it goes."""
    content, reasoning = [], []
    for raw in lines:
        line = raw.decode() if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            delta = json.loads(data)["choices"][0].get("delta", {})
        except (ValueError, KeyError, IndexError):
            continue
        if delta.get("reasoning_content"):
            reasoning.append(delta["reasoning_content"])
        if delta.get("content"):
            content.append(delta["content"])
        if on_progress is not None:
            on_progress("".join(reasoning), "".join(content))
    return "".join(content), "".join(reasoning) or None


def recording_llm(llm, path, every=1.5):
    """Wrap an LLM client so every call is appended to `path` (JSON lines): a `start` record (seat, tier, prompt)
    before the call, `progress` records (the latest reasoning, at most every `every` seconds) while a streaming client
    reports it, and an `end` record after it (reply, reasoning, timing, error). The lab floor reads this to show who is
    thinking and what; the lab itself never reads it, so it cannot influence a decision."""
    import inspect
    import itertools
    import os
    import re
    import time

    counter = itertools.count(1)
    streams = "on_progress" in inspect.signature(llm).parameters

    def write(rec):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def llm_rec(prompt, system=None, tier=None):
        call = next(counter)
        m = re.match(r"You are (\S+?),", system or "")
        seat = m.group(1) if m else None
        t0 = time.time()
        write(dict(event="start", call=call, seat=seat, tier=tier, t=t0, prompt=prompt))
        last = [0.0]

        def progress(reasoning, content):
            now = time.time()
            if now - last[0] >= every:
                last[0] = now
                write(dict(event="progress", call=call, seat=seat, t=now, reasoning_tail=reasoning[-1200:],
                           reasoning_chars=len(reasoning), reply_chars=len(content)))  # fmt: skip

        try:
            reply = (
                llm(prompt, system=system, tier=tier, on_progress=progress)
                if streams
                else llm(prompt, system=system, tier=tier)
            )
        except Exception as e:
            write(dict(event="end", call=call, seat=seat, tier=tier, t=time.time(), s=round(time.time() - t0, 2),
                       system=system, prompt=prompt, reply=None, error=f"{type(e).__name__}: {e}"))  # fmt: skip
            raise
        write(dict(event="end", call=call, seat=seat, tier=tier, t=time.time(), s=round(time.time() - t0, 2),
                   system=system, prompt=prompt, reply=str(reply), reasoning=getattr(reply, "reasoning", None),
                   error=None))  # fmt: skip
        return reply

    return llm_rec
