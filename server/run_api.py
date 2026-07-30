from __future__ import annotations

import os

import uvicorn

from app import app


def _resolve_port() -> int:
    raw = str(os.getenv("PORT") or "").strip()
    try:
        value = int(raw)
    except Exception:
        return 8000
    return value if value > 0 else 8000


def main() -> None:
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=_resolve_port(),
        reload=False,
    )


if __name__ == "__main__":
    main()
