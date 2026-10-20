"""Publish the GGUF runtime artifacts + model card to a public Hugging Face model repo.

    HF_TOKEN=... python hf_model/publish.py --repo <hf-user>/geoai-outdoor-qwen3-1.7b-gguf \
        --gguf-dir hf_model/work/out

If --gguf-dir is omitted, the model card, prompts and license are published and the GGUF files are
copied from the upstream Apache-2.0 GGUF repo (unsloth/Qwen3-1.7B-GGUF), with attribution in the card.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

HERE = Path(__file__).resolve().parent
UPSTREAM_REPO = "unsloth/Qwen3-1.7B-GGUF"
UPSTREAM_FILES = {"Qwen3-1.7B-Q4_K_M.gguf": "qwen3-1.7b-q4_k_m.gguf", "Qwen3-1.7B-Q8_0.gguf": "qwen3-1.7b-q8_0.gguf"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--gguf-dir", type=Path)
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is required")
    api = HfApi(token=token)
    api.create_repo(args.repo, repo_type="model", private=args.private, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copy(HERE / "README.md", stage / "README.md")
        shutil.copy(HERE / "LICENSE", stage / "LICENSE")
        shutil.copytree(HERE / "prompts", stage / "prompts")
        if (HERE / "eval").exists():
            shutil.copytree(HERE / "eval", stage / "eval")
        shutil.copy(HERE / "quantize.sh", stage / "quantize.sh")
        if args.gguf_dir:
            for f in args.gguf_dir.iterdir():
                if f.suffix == ".gguf" or f.name in {"SHA256SUMS", "BUILD_INFO"}:
                    shutil.copy(f, stage / f.name)
        else:
            for src, dst in UPSTREAM_FILES.items():
                path = hf_hub_download(UPSTREAM_REPO, src)
                shutil.copy(path, stage / dst)
        api.upload_folder(folder_path=str(stage), repo_id=args.repo, repo_type="model",
                          commit_message="Publish GeoAI outdoor assistant SLM runtime artifacts")
    print(f"Published https://huggingface.co/{args.repo}")


if __name__ == "__main__":
    main()
