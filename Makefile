.PHONY: test lint api ui types eval

test:
	cd backend && .venv/bin/python -m pytest -q -p no:warnings
	cd frontend && pnpm test

lint:
	cd backend && .venv/bin/ruff check app tests scripts

api:
	cd backend && SLM_ENABLED=false .venv/bin/uvicorn app.main:app --reload --port 7860

ui:
	cd frontend && pnpm dev

types:
	cd backend && .venv/bin/python scripts/export_openapi.py
	cd frontend && pnpm gen:types

eval:
	cd backend && SLM_ENABLED=true MODEL_PATH=models/Qwen3-1.7B-Q4_K_M.gguf .venv/bin/python scripts/eval_intent.py --slm --out ../hf_model/eval/intent_eval.json
