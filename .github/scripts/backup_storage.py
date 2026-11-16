"""Baixa todos os arquivos do Supabase Storage (todos os buckets) para uma pasta local.

O backup diário do Supabase cobre só o banco; artes, Biblioteca e miniaturas ficam no Storage e não voltam
numa restauração. Este script roda no workflow de backup, que compacta, criptografa e envia a pasta para fora.

Uso: python backup_storage.py <pasta_destino>
Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (lidas do segredo MUGO_JOBS_ENV pelo workflow).
Log público: só totais (buckets, arquivos, bytes, falhas). Nunca nomes de arquivo nem conteúdo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator, List
from urllib.parse import quote

import httpx

PAGE = 1000


def _client() -> httpx.Client:
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
    return httpx.Client(base_url=os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1", timeout=120,
                        headers={"Authorization": f"Bearer {key}", "apikey": key})


def buckets(client: httpx.Client) -> List[str]:
    response = client.get("/bucket")
    response.raise_for_status()
    return [b["id"] for b in response.json()]


def walk(client: httpx.Client, bucket: str, prefix: str = "") -> Iterator[str]:
    """Todos os caminhos de arquivo do bucket (pastas são percorridas recursivamente)."""
    offset = 0
    while True:
        response = client.post(f"/object/list/{bucket}", json={"prefix": prefix, "limit": PAGE, "offset": offset,
                                                               "sortBy": {"column": "name", "order": "asc"}})
        response.raise_for_status()
        items = response.json()
        for item in items:
            path = f"{prefix}{item['name']}"
            if item.get("id") is None:  # pasta
                yield from walk(client, bucket, f"{path}/")
            else:
                yield path
        if len(items) < PAGE:
            return
        offset += PAGE


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: backup_storage.py <pasta_destino>")
        return 2
    target = Path(sys.argv[1])
    files = size = failed = 0
    with _client() as client:
        names = buckets(client)
        for bucket in names:
            for path in walk(client, bucket):
                dest = target / bucket / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with client.stream("GET", f"/object/authenticated/{bucket}/{quote(path)}") as response:
                        response.raise_for_status()
                        with open(dest, "wb") as fh:
                            for chunk in response.iter_bytes():
                                fh.write(chunk)
                    files += 1
                    size += dest.stat().st_size
                except httpx.HTTPError:
                    failed += 1
    print(f"storage buckets={len(names)} arquivos={files} bytes={size} falhas={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
