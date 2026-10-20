"""Write the OpenAPI document used to generate the frontend types (frontend/src/api/schema.d.ts).

    python scripts/export_openapi.py [--out ../frontend/openapi.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"))
    args = ap.parse_args()
    app = create_app(Settings(slm_enabled=False))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=False) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
