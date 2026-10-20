"""Phase 0 gate: measure llama.cpp throughput for the two production prompt shapes.

Usage:
    MODEL_PATH=models/Qwen3-1.7B-Q4_K_M.gguf N_THREADS=2 python scripts/bench_model.py

Gate (plan section E, Phase 0): generation >= 6 tok/s and explanation-shaped call <= 50 s.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.slm.runtime import LlamaCppRuntime, build_chatml_prompt  # noqa: E402

FILLER_FACT = "F{i}: Forecast heat index 31 C at 07:00 local (Open-Meteo, derived). "
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "why": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["summary", "why"],
}


def run(rt: LlamaCppRuntime, prompt_words: int, max_tokens: int) -> dict:
    facts = "".join(FILLER_FACT.format(i=i) for i in range(prompt_words // 14))
    prompt = build_chatml_prompt(
        "You explain outdoor recommendations using only the facts given. Output JSON.",
        f"Facts: {facts}\nWrite a summary and up to four reasons.",
    )
    start = time.monotonic()
    res = rt._generate_sync(prompt, SCHEMA, max_tokens=max_tokens, temperature=0.3, deadline=start + 300)
    gen_tps = res.completion_tokens / res.seconds if res.seconds else 0
    return {
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
        "seconds": round(res.seconds, 2),
        "overall_completion_tok_per_s": round(gen_tps, 2),
    }


def main() -> int:
    settings = get_settings()
    rt = LlamaCppRuntime(settings)
    rt.load()
    if not rt.is_loaded:
        print(json.dumps({"error": rt.load_error}))
        return 2
    results = {
        "model_path": settings.model_path,
        "n_threads": settings.n_threads,
        "n_gpu_layers": settings.n_gpu_layers,
        "load_seconds": rt.load_seconds,
        "intent_shape": run(rt, prompt_words=350, max_tokens=160),
        "explain_shape": run(rt, prompt_words=900, max_tokens=380),
    }
    explain = results["explain_shape"]
    results["gate_pass"] = explain["seconds"] <= 50 and explain["overall_completion_tok_per_s"] >= 3
    print(json.dumps(results, indent=2))
    return 0 if results["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
