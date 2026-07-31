from __future__ import annotations

import os
import re

from .env_loader import ensure_env_loaded


DEFAULT_META_GRAPH_VERSION = "v25.0"
_GRAPH_VERSION_PATTERN = re.compile(r"^v\d+\.\d+$")

ensure_env_loaded()


def resolve_meta_graph_version() -> str:
    configured = (os.getenv("META_GRAPH_VERSION") or "").strip()
    if not configured:
        return DEFAULT_META_GRAPH_VERSION
    if not _GRAPH_VERSION_PATTERN.fullmatch(configured):
        raise RuntimeError(
            "META_GRAPH_VERSION inválida. Use o formato vN.N, por exemplo v25.0."
        )
    return configured


META_GRAPH_VERSION = resolve_meta_graph_version()
META_GRAPH_BASE_URL = f"https://graph.facebook.com/{META_GRAPH_VERSION}"
META_OAUTH_DIALOG_URL = (
    f"https://www.facebook.com/{META_GRAPH_VERSION}/dialog/oauth"
)
