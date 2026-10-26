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
        self._thinking_ok = True
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
        model = self.vision_model if images else (self.deep_model if purpose.startswith("hire:") else self.model)
        cfg = self._config(purpose, temperature, max_tokens)

        last_err = None
        for _attempt, backoff in enumerate((3, 8, 20, 0)):
            t0 = time.time()
            try:
                resp = self.client.models.generate_content(model=model, contents=contents, config=cfg)
                text = resp.text or ""
                self._count(purpose, model, prompt, text, time.time() - t0, bool(images))
                return text
            except Exception as e:
                last_err = e
                msg = str(e)
                if self._thinking_ok and "thinking" in msg.lower() and ("400" in msg or "INVALID_ARGUMENT" in msg):
                    self._thinking_ok = False  # this model/API version rejects the thinking setting: stop sending it
                    cfg = self._config(purpose, temperature, max_tokens)
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
        raise LLMUnavailable(f"Gemma call failed: {last_err}")

    def thinking_level(self, purpose: str) -> str:
        """How hard Gemma should think for this call ('' = the model's default)."""
        level = config.GEMMA_THINKING_DEEP if purpose.startswith("hire:") else config.GEMMA_THINKING
        return level if self._thinking_ok else ""

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
        except ValueError:
            fix = self.generate(
                "The following was supposed to be valid JSON but is not. Return the corrected JSON only.\n\n" + text,
                purpose=purpose + ":json-repair",
            )
            return parse_json(fix)

    def _count(self, purpose, model, prompt, text, seconds, vision) -> None:
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
                }
            )
        counter = CALL_COUNTER.get()
        if counter is not None:
            counter["n"] = counter.get("n", 0) + 1


def parse_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found")
    start = min(starts)
    end = max(t.rfind("}"), t.rfind("]"))
    candidate = t[start : end + 1]
    for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    raise ValueError("invalid JSON")


llm = Gemma()
