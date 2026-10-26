"""Gemma 4 through the Gemini API (google-genai SDK).

- Auto-detects a Gemma 4 model if GEMMA_MODEL is not set.
- Every call is counted (per task, via a context variable) and traced, so the console can show
  how many AI calls each task needed and how learning reduces them.
- No system-instruction field is used (Gemma models on the API take instructions in the user turn).
- JSON is requested in the prompt and parsed defensively, with one "fix your JSON" retry.
"""

import contextvars
import json
import re
import threading
import time
from collections import deque
from typing import Any

from .. import config


class LLMUnavailable(RuntimeError):
    pass


# per-task call counter: runner sets a dict {"n": 0}; every call increments it
CALL_COUNTER: contextvars.ContextVar[dict | None] = contextvars.ContextVar("CALL_COUNTER", default=None)


class Gemma:
    def __init__(self) -> None:
        self.client: Any = None
        self._types: Any = None
        self.model = config.GEMMA_MODEL
        self.vision_model = config.GEMMA_VISION_MODEL
        self.deep_model = config.GEMMA_DEEP_MODEL
        self.mode = "offline"
        self.error = ""
        self.total_calls = 0
        self._bad_levels: set[str] = set()
        self._limits: dict[str, tuple[int | None, int | None]] | None = None  # model -> (input, output) tokens
        self.last_error = ""
        self.trace: deque = deque(maxlen=200)
        self._lock = threading.Lock()
        self._init()

    # ------------------------------------------------------------------ setup
    def _init(self) -> None:
        if config.LLM_MODE == "offline" or not config.GEMINI_API_KEY:
            self.mode = "offline"
            self.error = "No GEMINI_API_KEY set" if not config.GEMINI_API_KEY else "LLM_MODE=offline"
            return
        try:
            from google import genai
            from google.genai import types

            self._types = types
            self.client = genai.Client(
                api_key=config.GEMINI_API_KEY,
                http_options=types.HttpOptions(timeout=int(config.LLM_TIMEOUT_S * 1000)),
            )
            if not self.model:
                self.model = self._detect_model()
            if not self.vision_model:
                self.vision_model = self.model
            if not self.deep_model:
                self.deep_model = self.model
            self.mode = "live"
        except Exception as e:
            self.mode = "offline"
            self.error = f"Gemini client init failed: {e}"

    def _detect_model(self) -> str:
        names = [m.name.split("/")[-1] for m in self.client.models.list()]
        gemma4 = [n for n in names if n.startswith("gemma-4")]
        candidates = gemma4 or [n for n in names if n.startswith("gemma")]
        if not candidates:
            raise LLMUnavailable("No Gemma model visible to this API key")

        def size(n: str) -> float:
            m = re.search(r"(\d+(?:\.\d+)?)b", n)
            return float(m.group(1)) if m else 0.0

        instruct = [n for n in candidates if "it" in n.split("-")] or candidates
        return max(instruct, key=size)

    def limits(self, model: str) -> tuple[int | None, int | None]:
        """(input, output) token limits Google publishes for a model — read once from the API."""
        if self._limits is None:
            self._limits = {}
            try:
                for m in self.client.models.list():
                    if "gemma" in m.name:
                        name = m.name.split("/")[-1]
                        self._limits[name] = (m.input_token_limit, m.output_token_limit)
            except Exception:
                pass  # limits are an optimisation; calls still work without them
        return self._limits.get(model, (None, None))

    def list_models(self) -> list[str]:
        if not self.client:
            return []
        return [m.name.split("/")[-1] for m in self.client.models.list() if "gemma" in m.name]

    @property
    def live(self) -> bool:
        return self.mode == "live"

    # ------------------------------------------------------------------ calls
    def generate(
        self,
        prompt: str,
        images: list[bytes] | None = None,
        purpose: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        if not self.live:
            raise LLMUnavailable(self.error or "offline")
        types = self._types
        contents: list = []
        for img in images or []:
            contents.append(types.Part.from_bytes(data=img, mime_type="image/png"))
        contents.append(prompt)
        deep = purpose.startswith("hire:")
        model = self.vision_model if images else (self.deep_model if deep else self.model)
        if deep:  # room to reason AND to write a whole plan
            max_tokens = max(max_tokens, config.GEMMA_DEEP_MAX_TOKENS)
        out_limit = self.limits(model)[1]
        max_tokens = min(max_tokens, out_limit or SAFE_MAX_TOKENS)  # never ask for more than the model can give

        last_err: Exception | None = None
        for _attempt, backoff in enumerate((3, 8, 20, 0)):
            cfg = self._config(purpose, temperature, max_tokens)
            t0 = time.time()
            try:
                resp = self.client.models.generate_content(model=model, contents=contents, config=cfg)
            except Exception as e:
                last_err = e
                msg = str(e)
                bad_request = "400" in msg or "INVALID_ARGUMENT" in msg
                level = self.thinking_level(purpose)
                if bad_request and level and "think" in msg.lower():
                    self._bad_levels.add(level)  # this model rejects that thinking level: stop sending it
                    continue
                if bad_request and "token" in msg.lower() and max_tokens > 8192:
                    max_tokens = 8192  # model has a smaller output limit
                    continue
                if ("500" in msg or "INTERNAL" in msg) and max_tokens > 8192:
                    max_tokens = 8192  # big answer budgets can make the hosted model fail with a bare 500
                    continue
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:  # per-minute quota: wait as long as Google asks
                    m = re.search(r"retry(?:_?delay)?\W+(\d+)", msg, re.IGNORECASE)
                    wait = min(int(m.group(1)) + 1, 60) if m else max(backoff, 15)
                    if backoff:
                        self.last_error = f"{purpose}: per-minute quota reached, waiting {wait}s"
                        time.sleep(wait)
                        continue
                transient = (
                    any(s in msg for s in ("429", "RESOURCE_EXHAUSTED", "503", "500", "UNAVAILABLE"))
                    or "timeout" in msg.lower()
                    or "timed out" in msg.lower()
                )
                if transient and backoff:
                    time.sleep(backoff)
                    continue
                break
            text = resp.text or ""
            info = _usage(resp)
            self._count(purpose, model, prompt, text, time.time() - t0, bool(images), info)
            if not text.strip():
                self.last_error = (
                    f"{purpose}: empty answer (finish={info['finish'] or '?'}, thinking tokens={info['thoughts']})"
                )
                raise LLMUnavailable(self.last_error)
            return text
        self.last_error = f"{purpose}: Gemma call failed: {last_err}"
        raise LLMUnavailable(self.last_error)

    def thinking_level(self, purpose: str) -> str:
        """How hard Gemma should think for this call ('' = the model's default)."""
        level = config.GEMMA_THINKING_DEEP if purpose.startswith("hire:") else config.GEMMA_THINKING
        return "" if level in self._bad_levels else level

    def _config(self, purpose: str, temperature: float, max_tokens: int) -> Any:
        types = self._types
        level = self.thinking_level(purpose)
        extra = {"thinking_config": types.ThinkingConfig(thinking_level=level.upper())} if level else {}
        return types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens, **extra)

    def generate_json(self, prompt: str, images: list[bytes] | None = None, purpose: str = "", **kw):
        text = self.generate(
            prompt + "\n\nReturn ONLY valid JSON. No markdown, no explanations.", images=images, purpose=purpose, **kw
        )
        try:
            return parse_json(text)
        except ValueError as first:
            self.last_error = f"{purpose}: {first} — asking Gemma to repair it"
            fix = self.generate(
                "The following was supposed to be valid JSON but is not. Return the corrected JSON only.\n\n" + text,
                purpose=purpose + ":json-repair",
                **kw,
            )
            try:
                return parse_json(fix)
            except ValueError as e:
                self.last_error = f"{purpose}: {e} (also after repair)"
                raise

    def _count(self, purpose, model, prompt, text, seconds, vision, info: dict | None = None) -> None:
        with self._lock:
            self.total_calls += 1
            self.trace.appendleft(
                {
                    "ts": time.strftime("%H:%M:%S"),
                    "purpose": purpose,
                    "model": model,
                    "vision": vision,
                    "prompt_chars": len(prompt),
                    "output_chars": len(text),
                    "seconds": round(seconds, 2),
                    **(info or {}),
                }
            )
        counter = CALL_COUNTER.get()
        if counter is not None:
            counter["n"] = counter.get("n", 0) + 1


def _usage(resp: Any) -> dict:
    """Thinking tokens, answer tokens and why the model stopped — shown in the Gemma trace."""
    u = getattr(resp, "usage_metadata", None)
    cands = getattr(resp, "candidates", None) or []
    finish = getattr(cands[0], "finish_reason", None) if cands else None
    return {
        "thoughts": getattr(u, "thoughts_token_count", None) if u else None,
        "out_tokens": getattr(u, "candidates_token_count", None) if u else None,
        "finish": str(getattr(finish, "name", finish) or ""),
    }


SAFE_MAX_TOKENS = 8192  # used when Google does not publish a model's output limit

_THOUGHTS = re.compile(r"<(think|thought|thinking)>.*?</\1>", re.DOTALL | re.IGNORECASE)


def parse_json(text: str):
    """The largest valid JSON value in the answer (ignores reasoning text, fences and small inline examples)."""
    t = _THOUGHTS.sub("", text or "").replace("```json", "```")
    dec = json.JSONDecoder()
    best: tuple[int, Any] | None = None
    i, n = 0, len(t)
    while i < n:
        if t[i] in "{[":
            try:
                obj, end = dec.raw_decode(t, i)
            except json.JSONDecodeError:
                i += 1
                continue
            if best is None or end - i > best[0]:
                best = (end - i, obj)
            i = end  # skip what's inside this value
            continue
        i += 1
    if best is not None:
        return best[1]
    starts = [k for k in (t.find("{"), t.find("[")) if k != -1]
    if not starts:
        raise ValueError("no JSON found")
    candidate = t[min(starts) : max(t.rfind("}"), t.rfind("]")) + 1]
    try:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))  # tolerate trailing commas
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON ({e.msg})") from e


llm = Gemma()
