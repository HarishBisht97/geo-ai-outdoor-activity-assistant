---
license: apache-2.0
base_model: Qwen/Qwen3-1.7B
base_model_revision: 70d244cc86ccca08cf5af4e1e306ecf908b1ad5e
library_name: transformers
tags:
  - qwen3
  - gguf
  - llama.cpp
  - geoai
  - outdoor
pipeline_tag: text-generation
---

# GeoAI Outdoor Activity Assistant — Qwen3-1.7B GGUF runtime

Quantized runtime of **[Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B)** (2,031,739,904 parameters, Apache-2.0) used by the GeoAI Outdoor Activity Recommendation Assistant. The small language model runs **in-process** with llama.cpp on CPU. It never ranks places or times; a deterministic engine does that. The model only (1) extracts structured intent from a question and (2) writes a short explanation of already-ranked options, constrained by a JSON grammar and a claim validator.

## Files

| File | Role |
| --- | --- |
| `qwen3-1.7b-q4_k_m.gguf` | Production weights (Q4_K_M). Baked into the Hugging Face Space image. |
| `qwen3-1.7b-q8_0.gguf` | Higher-fidelity fallback. |
| `prompts/` | Byte-stable ChatML system prompts and JSON Schemas (`PROMPT_VERSION` in `prompts/VERSION`). |
| `eval/intent_eval.json` | Latest intent-extraction metrics. |
| `quantize.sh` | Reproducible conversion from the pinned base revision. |

The Q4_K_M file currently served is the community conversion [`unsloth/Qwen3-1.7B-GGUF`](https://huggingface.co/unsloth/Qwen3-1.7B-GGUF) `Qwen3-1.7B-Q4_K_M.gguf` (sha256 `b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897`). `quantize.sh` rebuilds both files from the base checkpoint with llama.cpp `b11755`.

## How it is loaded

```python
from llama_cpp import Llama
llm = Llama(model_path="qwen3-1.7b-q4_k_m.gguf", n_ctx=4096, n_threads=2, logits_all=False)
```

ChatML with an empty think block (Qwen3 otherwise emits a reasoning trace that burns the token budget):

```
<|im_start|>system
{system}<|im_end|>
<|im_start|>user
{user}<|im_end|>
<|im_start|>assistant
<think>

</think>
```

JSON output is constrained with `llama_cpp.LlamaGrammar.from_json_schema`. Temperature is 0 for intent and 0.2 for explanation. Seed is 42.

## What the model is allowed to do

- **Intent:** emit the flat JSON in `prompts/intent_schema.json`. Location strings that do not appear in the question are dropped. Explicit activity / day / part-of-day tokens from a keyword parser override the model.
- **Explanation:** emit `summary`, `best`, `alternative`, `why` (≤2), `caveat`. Carry / watch-for / postpone advice is always a deterministic template. Every number, capitalised name and weather condition is checked against cited facts; failing items are removed (`removed_claims`).

The model is **not** used for geocoding, ranking, safety filters, or inventing venues.

## Evaluation (2026-10-20, Apple CPU, 2 threads)

Dataset: 60 labelled questions in `backend/tests/data/intent_eval.jsonl` (all 10 activities, the 8 brief examples, unsupported activities, missing location, sensitive groups).

| System | Activity | Location | Day | Part of day | All fields | JSON valid | p50 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Keyword parser (fallback) | 1.00 | 0.97 | 1.00 | 1.00 | 0.95 | n/a | <1 ms |
| SLM raw | 0.93 | 0.98 | 0.60 | 0.83 | 0.42 | 1.00 | 7.9 s |
| **Final (SLM + reconcile)** | **0.97** | **1.00** | **0.98** | 0.83 | 0.72 | **1.00** | **7.9 s** |

Acceptance from the project plan: ≥90% activity, ≥90% location-span, zero invented locations, median ≤15 s. Final location accuracy is 1.00 (span check rejects names that are not in the question). p95 latency 14.3 s. Mean completion tokens 86.

## Intended use and limitations

Intended use: English questions about the ten supported outdoor activities, with a place in India or another OSM-mapped area, looking up to 7 days ahead.

Limitations: 1.7B parameters, Q4 quantization, CPU-only. The model will mis-label uncommon phrasings; the keyword parser is the safety net. It must not be used as medical advice. Air quality values it mentions come from a regional CAMS model, not a local sensor.

## License

Apache-2.0, inherited from Qwen3-1.7B. Quantization does not change the license. Please cite Qwen and this runtime repository if you redistribute.

## Citation

```
@misc{geoai-outdoor-qwen3,
  title={GeoAI Outdoor Activity Assistant runtime of Qwen3-1.7B},
  year={2026},
  howpublished={Hugging Face model repository}
}
```
