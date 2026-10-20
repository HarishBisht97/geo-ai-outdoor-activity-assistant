"""Hit a deployed API. Used by CI after Space deploy and locally against localhost.

    python scripts/smoke_test.py https://USER-SPACE.hf.space
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="API origin, e.g. http://127.0.0.1:7860")
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    base = args.base.rstrip("/")
    t0 = time.monotonic()
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        h = c.get(f"{base}/health")
        h.raise_for_status()
        assert h.json().get("status") == "ok", h.text
        r = c.get(f"{base}/ready")
        assert r.status_code in (200, 503), r.text
        q = {"question": "Where can I go running tomorrow morning near Powai?"}
        rec = c.post(f"{base}/api/v1/recommend", json=q, timeout=args.timeout)
        rec.raise_for_status()
        body = rec.json()
        assert body["status"] in ("ok", "partial", "needs_clarification", "no_suitable_option", "insufficient_data"), body
        assert body["data_mode"] == "live"
        print(f"ok health={h.json()} ready={r.json().get('status')} rec={body['status']} {time.monotonic()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
