"""Self-hosted SLM runtime (llama.cpp via llama-cpp-python).

One model instance per process, executed on a dedicated single worker thread so blocking
inference never runs on the asyncio event loop. Each call has a wall-clock deadline that
is enforced inside the sampling loop (stopping criterion), so a timed-out call frees the
worker instead of generating in the background.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings
from app.core.errors import OverloadedError, SLMTimeoutError, SLMUnavailableError
from app.core.logging import log_event

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    stopped_by_deadline: bool


class TextGenerator(Protocol):
    @property
    def is_loaded(self) -> bool: ...

    def info(self) -> dict[str, Any]: ...

    async def generate_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        max_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> GenerationResult: ...


def build_chatml_prompt(system: str, user: str) -> str:
    """Qwen3 ChatML with an empty think block, equivalent to enable_thinking=False."""
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


class LlamaCppRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._llm = None
        self._grammars: dict[str, Any] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="slm")
        self._lock = asyncio.Semaphore(1)
        self._waiting = 0
        self.load_error: str | None = None
        self.load_seconds: float | None = None
        self.last_benchmark: dict[str, float] | None = None

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    def info(self) -> dict[str, Any]:
        return {
            "base_model": self.settings.model_base_id,
            "base_revision": self.settings.model_base_revision,
            "runtime_repo": self.settings.model_repo or None,
            "runtime_file": os.path.basename(self.settings.model_path),
            "quantization": self.settings.model_quant,
            "parameters": 2_031_739_904,
            "loaded": self.is_loaded,
            "load_error": self.load_error,
            "load_seconds": self.load_seconds,
        }

    def load(self) -> None:
        if self._llm is not None:
            return
        path = self.settings.model_path
        if not os.path.exists(path):
            self.load_error = f"model file not found at {path}"
            log_event(logger, "slm_load_failed", logging.ERROR, reason=self.load_error)
            return
        try:
            from llama_cpp import Llama, LlamaRAMCache
        except ImportError as exc:  # pragma: no cover - depends on optional install
            self.load_error = f"llama-cpp-python not installed: {exc}"
            log_event(logger, "slm_load_failed", logging.ERROR, reason=self.load_error)
            return
        start = time.monotonic()
        try:
            llm = Llama(
                model_path=path,
                n_ctx=self.settings.n_ctx,
                n_threads=self.settings.n_threads,
                n_gpu_layers=self.settings.n_gpu_layers,
                use_mmap=True,
                verbose=False,
            )
            llm.set_cache(LlamaRAMCache(capacity_bytes=256 << 20))
        except Exception as exc:  # noqa: BLE001
            self.load_error = f"model load failed: {exc}"
            log_event(logger, "slm_load_failed", logging.ERROR, reason=self.load_error)
            return
        self._llm = llm
        self.load_seconds = round(time.monotonic() - start, 2)
        self.load_error = None
        log_event(logger, "slm_loaded", path=os.path.basename(path), seconds=self.load_seconds)

    async def warmup(self, system: str, user: str, schema: dict[str, Any]) -> None:
        """Pages the weights in and caches the KV state of a static prompt prefix (the intent prompt)."""
        if self._llm is None:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(self._executor, lambda: self._generate_sync(
                build_chatml_prompt(system, user), schema, max_tokens=4, temperature=0.0,
                deadline=time.monotonic() + 120,
            ))
        log_event(logger, "slm_warmup", seconds=round(res.seconds, 2), prompt_tokens=res.prompt_tokens)

    def _grammar_for(self, schema: dict[str, Any]):
        from llama_cpp import LlamaGrammar

        key = json.dumps(schema, sort_keys=True)
        if key not in self._grammars:
            self._grammars[key] = LlamaGrammar.from_json_schema(key, verbose=False)
        return self._grammars[key]

    def _generate_sync(
        self, prompt: str, schema: dict[str, Any], *, max_tokens: int, temperature: float, deadline: float
    ) -> GenerationResult:
        from llama_cpp import StoppingCriteriaList

        assert self._llm is not None
        hit_deadline = {"v": False}

        def past_deadline(_ids, _logits) -> bool:
            if time.monotonic() > deadline:
                hit_deadline["v"] = True
                return True
            return False

        start = time.monotonic()
        out = self._llm.create_completion(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.8 if temperature > 0 else 1.0,
            top_k=20,
            repeat_penalty=1.05,
            seed=42,
            grammar=self._grammar_for(schema),
            stop=["<|im_end|>"],
            stopping_criteria=StoppingCriteriaList([past_deadline]),
        )
        usage = out.get("usage", {})
        return GenerationResult(
            text=out["choices"][0]["text"],
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            seconds=time.monotonic() - start,
            stopped_by_deadline=hit_deadline["v"],
        )

    async def generate_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        max_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> GenerationResult:
        if self._llm is None:
            raise SLMUnavailableError(self.load_error or "model not loaded")
        if self._waiting >= self.settings.slm_queue_max:
            raise OverloadedError("The language model queue is full, please retry shortly.", retry_after_s=20)
        self._waiting += 1
        try:
            queued_at = time.monotonic()
            async with self._lock:
                remaining = timeout_s - (time.monotonic() - queued_at)
                if remaining <= 1:
                    raise SLMTimeoutError("timed out waiting for the model")
                deadline = time.monotonic() + remaining
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    self._executor,
                    lambda: self._generate_sync(
                        build_chatml_prompt(system, user),
                        schema,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        deadline=deadline,
                    ),
                )
        finally:
            self._waiting -= 1
        log_event(
            logger,
            "slm_generation",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            seconds=round(result.seconds, 2),
            tok_per_s=round(result.completion_tokens / result.seconds, 2) if result.seconds else None,
            deadline_hit=result.stopped_by_deadline,
        )
        if result.stopped_by_deadline:
            raise SLMTimeoutError(f"generation exceeded {timeout_s:.0f}s")
        return result


class DisabledRuntime:
    """Used when SLM_ENABLED=false; every call falls back to deterministic paths."""

    is_loaded = False

    def info(self) -> dict[str, Any]:
        return {"loaded": False, "load_error": "SLM disabled by configuration"}

    async def generate_json(self, *args, **kwargs) -> GenerationResult:
        raise SLMUnavailableError("SLM disabled by configuration")
