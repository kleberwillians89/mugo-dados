"""Diagnósticos somente leitura que rodam no GitHub Actions (log público: só o código de saída sai de lá).

research-check            0 = Brave configurado e respondendo com resultados
                          10 = Brave não configurado (faltam EXTERNAL_RESEARCH_PROVIDER=brave e/ou BRAVE_SEARCH_API_KEY)
                          11 = configurado, mas a chamada falhou (chave inválida, cota, rede)
                          12 = configurado e respondendo, sem resultados para a marca testada
competitors-check         0 = a empresa tem concorrentes no Radar do Clipping
                          20 = Radar salvo, mas sem concorrentes
                          21 = Radar do Clipping não configurado nessa empresa
"""
from __future__ import annotations

from typing import Any, Dict

from .ig_supabase import sb_select


async def research_check(client_id: str) -> Dict[str, Any]:
    from .external_research import get_provider
    provider = get_provider()
    if provider is None:
        return {"exit_code": 10}
    try:
        rows = await provider.find_market_signals(client_id=client_id, query={})
    except Exception as exc:  # noqa: BLE001 — só o tipo do erro, nada da resposta
        return {"exit_code": 11, "error_type": type(exc).__name__}
    return {"exit_code": 0 if rows else 12, "results": len(rows or [])}


async def competitors_check(client_id: str) -> Dict[str, Any]:
    rows = await sb_select("studio_clipping_settings", select="competitor_terms", filters={"client_id": f"eq.{client_id}"}, limit=1)
    if not rows:
        return {"exit_code": 21}
    terms = [t for t in (rows[0].get("competitor_terms") or []) if str(t or "").strip()]
    return {"exit_code": 0 if terms else 20, "competitors": len(terms)}
