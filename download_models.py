"""
download_models.py — One-shot script to cache both ML models locally.

Run once after cloning (or when models/ is missing):
    python download_models.py

Downloads ~175 MB total into models/ so Agnes starts fully offline
with no HuggingFace network calls and no auth warnings.

Models saved:
    models/all-MiniLM-L6-v2/          — sentence embedding model
    models/cross-encoder-reranker/     — cross-encoder reranker
"""

from __future__ import annotations

import sys
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"
EMB_PATH   = MODELS_DIR / "all-MiniLM-L6-v2"
CE_PATH    = MODELS_DIR / "cross-encoder-reranker"


def _suppress_hf_noise() -> None:
    try:
        import os
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from transformers import logging as _hf_logging
        _hf_logging.set_verbosity_error()
    except Exception:
        pass


def _check_deps() -> None:
    missing = []
    for pkg in ("sentence_transformers",):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"Missing dependencies: {missing}")
        print("Install with: pip install sentence-transformers --break-system-packages")
        sys.exit(1)


def download_embedding_model() -> None:
    from sentence_transformers import SentenceTransformer
    if EMB_PATH.exists():
        print(f"  ✓  Embedding model already present: {EMB_PATH}")
        return
    print("  →  Downloading all-MiniLM-L6-v2 (~90 MB) …", flush=True)
    model = SentenceTransformer("all-MiniLM-L6-v2")
    model.save(str(EMB_PATH))
    size_mb = sum(f.stat().st_size for f in EMB_PATH.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"  ✓  Saved → {EMB_PATH}  ({size_mb:.0f} MB)")


def download_cross_encoder() -> None:
    from sentence_transformers import CrossEncoder
    if CE_PATH.exists():
        print(f"  ✓  Cross-encoder already present: {CE_PATH}")
        return
    print("  →  Downloading cross-encoder/ms-marco-MiniLM-L-6-v2 (~90 MB) …", flush=True)
    ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    ce.save(str(CE_PATH))
    size_mb = sum(f.stat().st_size for f in CE_PATH.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"  ✓  Saved → {CE_PATH}  ({size_mb:.0f} MB)")


if __name__ == "__main__":
    _suppress_hf_noise()
    print("\nAgnes — Model Downloader")
    print("─" * 40)
    _check_deps()
    MODELS_DIR.mkdir(exist_ok=True)
    download_embedding_model()
    download_cross_encoder()
    total_mb = sum(
        f.stat().st_size for f in MODELS_DIR.rglob("*") if f.is_file()
    ) / 1024 / 1024
    print(f"\n  All models ready — {total_mb:.0f} MB in {MODELS_DIR}")
    print("─" * 40)
