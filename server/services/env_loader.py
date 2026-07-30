from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _is_production_runtime() -> bool:
    if _env("RENDER").lower() == "true":
        return True
    explicit_env = _env("ENVIRONMENT").lower() or _env("APP_ENV").lower() or _env("PYTHON_ENV").lower()
    return explicit_env in {"production", "prod"}


@lru_cache(maxsize=1)
def ensure_env_loaded() -> List[str]:
    """
    Carrega dotenv apenas como fallback local, sem sobrescrever variáveis
    já fornecidas pelo ambiente do processo.

    Ordem de precedência:
    1) os.environ / variáveis do processo
    2) server/.env (somente local/dev)
    3) .env na raiz do projeto (fallback local/dev)
    """
    if _is_production_runtime():
        print("[env] dotenv skipped: production runtime detected")
        return []

    server_dir = Path(__file__).resolve().parents[1]
    project_root_dir = server_dir.parent

    candidates = [
        server_dir / ".env",
        project_root_dir / ".env",
    ]

    loaded_paths: List[str] = []
    for env_path in candidates:
        if not env_path.exists():
            continue
        load_dotenv(env_path, override=False)
        loaded_paths.append(str(env_path))

    if loaded_paths:
        print(f"[env] dotenv files loaded: {', '.join(loaded_paths)}")
    else:
        print("[env] dotenv files loaded: none")

    return loaded_paths
