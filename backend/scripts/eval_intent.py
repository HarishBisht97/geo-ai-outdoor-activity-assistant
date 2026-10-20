"""Intent-extraction evaluation on tests/data/intent_eval.jsonl.

Three systems are scored with the same per-field metrics:
  rules      - deterministic keyword/regex parser (the fallback)
  slm_raw    - the SLM's grammar-constrained JSON alone (no reconciliation)
  final      - what the API uses: SLM output reconciled with the rules (or the rules when the SLM fails)

    python scripts/eval_intent.py                       # rules only
    SLM_ENABLED=true python scripts/eval_intent.py --slm --out ../hf_model/eval_results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rapidfuzz import fuzz  # noqa: E402

from app.schemas.intent import Activity, ExtractedIntent  # noqa: E402
from app.slm import rule_parser  # noqa: E402
from app.slm.intent_parser import flat_to_intent, reconcile  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "tests" / "data" / "intent_eval.jsonl"
FIELDS = ("activity", "location", "day_ref", "part_of_day", "clock_time", "sensitivities", "group")


def load_cases(path: Path = DATA) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _act(i: ExtractedIntent) -> str | None:
    a = i.activity
    return a.value if isinstance(a, Activity) else a


def _loc_ok(pred: str | None, gold: str | None) -> bool:
    if gold is None or pred is None:
        return gold is None and pred is None
    p, g = pred.lower().strip(), gold.lower().strip()
    # the leading place name must match; extra qualifiers ("Powai, Mumbai") are accepted
    return fuzz.ratio(p, g) >= 85 or p.startswith(g) or g.startswith(p) and len(p) >= 4


def score_case(case: dict, i: ExtractedIntent) -> dict[str, bool]:
    return {
        "activity": _act(i) == case.get("activity"),
        "location": _loc_ok(i.location_text, case.get("location")),
        "day_ref": i.time.day_ref == case.get("day_ref", "unspecified"),
        "part_of_day": (i.time.part_of_day or None) == case.get("part_of_day"),
        "clock_time": i.time.clock_time == case.get("clock_time"),
        "sensitivities": sorted(i.sensitivities) == sorted(case.get("sensitivities", [])),
        "group": (i.group.children, i.group.elderly) == (case.get("children", False), case.get("elderly", False)),
    }


def summarize(rows: list[dict[str, bool]]) -> dict[str, float]:
    n = len(rows) or 1
    out = {f: round(sum(r[f] for r in rows) / n, 3) for f in FIELDS}
    out["all_fields"] = round(sum(all(r.values()) for r in rows) / n, 3)
    return out


def eval_rules(cases: list[dict]) -> dict:
    rows = [score_case(c, rule_parser.parse(c["q"])) for c in cases]
    return {"metrics": summarize(rows), "n": len(cases)}


async def eval_slm(cases: list[dict]) -> tuple[dict, dict, list[dict]]:
    from app.core.config import get_settings
    from app.slm.prompts import INTENT_SCHEMA, INTENT_SYSTEM, intent_user_prompt
    from app.slm.runtime import LlamaCppRuntime

    s = get_settings()
    rt = LlamaCppRuntime(s)
    rt.load()
    if not rt.is_loaded:
        raise SystemExit(f"model failed to load from {s.model_path} (set MODEL_PATH)")
    await rt.warmup(INTENT_SYSTEM, intent_user_prompt("Where can I go running tomorrow morning?"), INTENT_SCHEMA)
    raw_rows, final_rows, details, lat, valid, tokens = [], [], [], [], 0, []
    for c in cases:
        rules = rule_parser.parse(c["q"])
        t0 = time.perf_counter()
        slm_intent, err = None, None
        try:
            res = await rt.generate_json(INTENT_SYSTEM, intent_user_prompt(c["q"]), INTENT_SCHEMA,
                                         max_tokens=s.slm_intent_max_tokens, temperature=0.0,
                                         timeout_s=max(60.0, s.slm_intent_timeout_s))
            tokens.append(res.completion_tokens)
            slm_intent = flat_to_intent(json.loads(res.text))
            valid += 1
        except Exception as exc:  # noqa: BLE001 - every failure mode counts as invalid output
            err = type(exc).__name__
        lat.append(time.perf_counter() - t0)
        final = reconcile(slm_intent, rules, c["q"])[0] if slm_intent else rules
        raw = score_case(c, slm_intent) if slm_intent else dict.fromkeys(FIELDS, False)
        fin = score_case(c, final)
        raw_rows.append(raw)
        final_rows.append(fin)
        details.append({"q": c["q"], "error": err, "raw_wrong": [k for k, v in raw.items() if not v],
                        "final_wrong": [k for k, v in fin.items() if not v]})
        print(f"{lat[-1]:5.1f}s err={err} raw_wrong={details[-1]['raw_wrong']} final_wrong={details[-1]['final_wrong']} "
              f":: {c['q'][:60]}", file=sys.stderr)
    lat_sorted = sorted(lat)
    perf = {
        "json_valid_rate": round(valid / len(cases), 3),
        "fallback_rate": round(1 - valid / len(cases), 3),
        "latency_s_p50": round(statistics.median(lat), 2),
        "latency_s_p95": round(lat_sorted[min(len(lat) - 1, int(0.95 * len(lat)))], 2),
        "completion_tokens_mean": round(statistics.mean(tokens), 1) if tokens else None,
        "threads": s.n_threads,
        "model_file": Path(s.model_path).name,
    }
    return ({"metrics": summarize(raw_rows), "n": len(cases)},
            {"metrics": summarize(final_rows), "n": len(cases), **perf}, details)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slm", action="store_true", help="also evaluate the GGUF model (slow on CPU)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    cases = load_cases()[: args.limit] if args.limit else load_cases()
    report: dict = {"dataset": str(DATA.name), "n": len(cases), "rules": eval_rules(cases)}
    if args.slm:
        raw, final, details = asyncio.run(eval_slm(cases))
        report.update(slm_raw=raw, final=final, failures=[d for d in details if d["final_wrong"] or d["error"]])
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")


if __name__ == "__main__":
    main()
