"""Compact, token-bounded evidence packet for SLM stage 2."""

from __future__ import annotations

from app.schemas.responses import Fact
from app.slm.templates import RecSummary

MAX_CHARS = 4200  # ~1,100-1,200 tokens for Qwen tokenizer on English text


def build_packet(
    question: str,
    activity_label: str,
    window_text: str,
    recs: list[RecSummary],
    facts: list[Fact],
    general: list[Fact],
    requested_first: bool = False,
) -> str:
    by_id = {f.id: f for f in facts}
    lines = [f"User question: {question}", f"Activity: {activity_label}. Time window: {window_text}."]
    if requested_first and recs:
        lines.append("R1 is the place the user asked about; it is listed first because it was named, not because "
                     "it scored highest. Answer whether it suits the activity; R2 and R3 are nearby alternatives.")
    lines.append("")
    for r in recs[:3]:
        lines.append(f"{r.prefix} = {r.label} ({r.status}), {r.slot_text}")
        for fid in r.facts.ids.values():
            f = by_id.get(fid)
            if f:
                lines.append(f"  {f.id}: {f.text}")
        lines.append("")
    if general:
        lines.append("General facts:")
        for f in general[:4]:
            lines.append(f"  {f.id}: {f.text}")
        lines.append("")
    packet = "\n".join(lines)
    if len(packet) > MAX_CHARS:
        packet = packet[:MAX_CHARS].rsplit("\n", 1)[0]
    return packet + "\n\nWrite the JSON explanation now."
