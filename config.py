import json
import os
from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    CONFIG_PATH = local_app_data / "PhotoSearch" / "config.json"
else:
    CONFIG_PATH = Path(__file__).with_name("config.json")

DEFAULTS = {
    "photo_folders": [],
    "recursive": True,
    "extensions": [".jpg", ".jpeg", ".heic", ".heif"],
    "exif_db_path": "data/exif.sqlite",
    "vector_db_path": "data/chroma",
    "chroma_collection": "photo_descriptions",
    "llm_base_url": "http://localhost:1234/v1",
    "llm_api_key": "not-needed",
    "llm_model": "local-model",
    "llm_temperature": 0.2,
    "embed_base_url": "http://localhost:1234/v1",
    "embed_api_key": "not-needed",
    "embed_model": "nomic-embed-text",
    "embed_batch_size": 16,
    "embed_workers": 4,
    "search_candidates": 15,
    "search_max_results": 5,
    "use_llm_rerank": True,
    "request_timeout": 120,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    else:
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else CONFIG_PATH.parent / p
