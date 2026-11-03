"""Mede a descoberta de ativos Meta (callback do OAuth) com a Graph API simulada.

Não chama a Meta: cada chamada espera LATENCY_MS e devolve dados sintéticos de uma conta de agência
(N páginas com Instagram, B businesses, A contas de anúncio). Mede o tempo de parede e conta as chamadas.
O tempo real depende da latência real da Meta: aqui o que importa é a forma (quantas chamadas, quantas
em sequência). Uso: python scripts/bench_meta_discovery.py [páginas] [businesses] [contas] [latência_ms]
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SUPABASE_URL", "https://bench.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "x" * 40)

from services import meta_oauth  # noqa: E402

PAGES, BUSINESSES, ADS, LATENCY_MS = (int(a) for a in (sys.argv[1:5] + ["40", "3", "20", "250"][len(sys.argv[1:5]):]))
calls: Counter = Counter()
inflight = {"now": 0, "max": 0}


def _page(i):
    return {"id": f"p{i}", "name": f"Página {i}", "instagram_business_account": {"id": f"ig{i}", "username": f"ig{i}"}}


def _response(path: str):
    p = path.split("?", 1)[0]
    if p.endswith("/me/accounts"):
        return {"data": [_page(i) for i in range(PAGES)]}
    if p.endswith("/me/adaccounts"):
        return {"data": [{"id": f"act_{i}", "account_id": str(i), "name": f"Conta {i}", "account_status": 1} for i in range(ADS)]}
    if p.endswith("/me/businesses"):
        return {"data": [{"id": f"b{i}", "name": f"BM {i}"} for i in range(BUSINESSES)]}
    if p.endswith("/me/permissions"):
        return {"data": [{"permission": s, "status": "granted"} for s in meta_oauth._default_scopes()]}
    if p.endswith("/me"):
        return {"id": "u1", "name": "Agência"}
    if "debug_token" in p:
        return {"data": {"granular_scopes": []}}
    if any(p.endswith(edge) for edge in ("owned_pages", "client_pages", "owned_instagram_accounts", "client_instagram_assets",
                                         "owned_ad_accounts", "client_ad_accounts")):
        return {"data": []}
    if "/p" in p:
        return _page(p.rsplit("/p", 1)[1])
    if "/act_" in p:
        return {"id": p.rsplit("/", 1)[1], "name": "Conta", "account_status": 1}
    return {}


async def fake_meta_get_json(path, params=None, **_kw):
    key = path.split("?", 1)[0].replace(meta_oauth.META_BASE if hasattr(meta_oauth, "META_BASE") else "", "")
    calls[_label(key)] += 1
    inflight["now"] += 1
    inflight["max"] = max(inflight["max"], inflight["now"])
    try:
        await asyncio.sleep(LATENCY_MS / 1000)
        return _response(path)
    finally:
        inflight["now"] -= 1


def _label(path: str) -> str:
    tail = path.rstrip("/").rsplit("/", 2)
    last = tail[-1]
    if last.startswith("p") and last[1:].isdigit():
        return "/{page_id} (detalhe por página)"
    if last.startswith("act_"):
        return "/{act_id} (verificação)"
    if tail[-2:] and len(tail) >= 2 and tail[-2].startswith("b") and tail[-2][1:].isdigit():
        return f"/{{business}}/{last}"
    return "/" + last


async def main() -> None:
    meta_oauth.meta_get_json = fake_meta_get_json
    started = time.perf_counter()
    out = await meta_oauth.discover_assets("token-de-teste")
    elapsed = time.perf_counter() - started
    total = sum(calls.values())
    print(f"cenario paginas={PAGES} businesses={BUSINESSES} contas={ADS} latencia_ms={LATENCY_MS}")
    print(f"descoberta_s={elapsed:.2f} chamadas={total} sequenciais_equivalentes={elapsed / (LATENCY_MS / 1000):.1f} "
          f"paralelas_max={inflight['max']}")
    print(f"ativos paginas={len(out['pages'])} instagram={len(out['instagram_accounts'])} contas={len(out['ad_accounts'])}")
    for label, count in calls.most_common():
        print(f"  {count:4d}  {label}")


if __name__ == "__main__":
    asyncio.run(main())
