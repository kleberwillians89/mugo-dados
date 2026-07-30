from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from dotenv import dotenv_values

from services.ig_dashboard import get_dashboard
from services.comments import get_comments, top_words
from services.media import get_media

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _env(name: str) -> Optional[str]:
    v = os.getenv(name)
    if v and str(v).strip():
        return str(v).strip()
    vals = dotenv_values(ENV_PATH)
    vv = vals.get(name)
    return str(vv).strip() if vv else None


def _need(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"{name} não configurado no .env (lido em {ENV_PATH})")
    return v


def _extract_output_text(resp: Dict[str, Any]) -> str:
    if isinstance(resp.get("output_text"), str) and resp["output_text"].strip():
        return resp["output_text"].strip()

    out = resp.get("output") or []
    for item in out:
        content = item.get("content") or []
        for block in content:
            if block.get("type") in ("output_text", "text") and isinstance(block.get("text"), str):
                t = block["text"].strip()
                if t:
                    return t
    return ""


AI_SCHEMA = {
    "name": "mugo_metrics_ai_report_v2",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "insights": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 7},
            "content_opportunities": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 7},
            "risks": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
            "next_actions": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 8},
            "data_quality_note": {"type": "string"},
        },
        "required": [
            "insights",
            "content_opportunities",
            "risks",
            "next_actions",
            "data_quality_note",
        ],
    },
}


async def _call_openai_json(prompt: str) -> Dict[str, Any]:
    api_key = _need("OPENAI_API_KEY")
    model = _env("OPENAI_MODEL") or "gpt-4.1-mini"

    payload = {
        "model": model,
        "instructions": "Você é um estrategista sênior de social media para agência. Nunca invente dados.",
        "input": prompt,
        "temperature": 0.35,
        "text": {
            "format": {
                "type": "json_schema",
                "name": AI_SCHEMA["name"],
                "schema": AI_SCHEMA["schema"],
            }
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI error {r.status_code}: {r.text}")

        data = r.json()
        text = _extract_output_text(data)
        if not text:
            raise RuntimeError("OpenAI não retornou texto (output vazio).")

        try:
            return json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise RuntimeError(f"Falha ao converter JSON da IA: {text[:300]}")


async def ai_summary(
    client_id: Optional[str] = None,
    days: int = 30,
    month: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, Any]:
    if not client_id:
        raise RuntimeError("client_id é obrigatório")

    sample_days = max(7, min(90, days))

    dash = await get_dashboard(
        client_id=client_id,
        days=sample_days,
        month=month,
        start=start,
        end=end,
    )
    comments_payload = await get_comments(
        client_id=client_id,
        days=sample_days,
        start=start,
        end=end,
    )
    comments = comments_payload.get("comments") or []

    media_payload = await get_media(client_id=client_id, days=sample_days, start=start, end=end)
    media = media_payload.get("media") or []

    top_words_from_comments = top_words(comments, limit=20)

    context = {
        "days": dash.get("days", sample_days),
        "start": dash.get("start") or start,
        "end": dash.get("end") or end,
        "month": month,
        "totals_last_days": dash.get("totals_last_days") or {},
        "totals_previous_period": dash.get("totals_previous_period") or {},
        "period_growth_percent": dash.get("period_growth_percent") or {},
        "monthly_totals": dash.get("monthly_totals") or {},
        "last_month_totals": dash.get("last_month_totals") or {},
        "followers_growth_last_days": dash.get("followers_growth_last_days") or 0,
        "daily": (dash.get("daily") or [])[-90:],
        "media_last_90d": media,
        "comments_last_90d": comments,
        "top_words": top_words_from_comments,
    }

    if not comments:
        data_quality_hint = "Sem comentários no período: sinalize limitação e foque em métricas de alcance/interação."
    else:
        data_quality_hint = "Comentários presentes: usar top palavras para inferir temas de interesse."

    prompt = (
        "Analise o desempenho do Instagram com base no JSON abaixo.\n"
        "Entregue saída prática para agência.\n"
        "Regras:\n"
        "- Não inventar números ou fatos fora do JSON.\n"
        "- Se faltar dado (principalmente comentários), declarar limitação explicitamente.\n"
        "- Priorize recomendações executáveis para os próximos 30 dias.\n"
        f"- {data_quality_hint}\n\n"
        f"JSON:\n{json.dumps(context, ensure_ascii=False)}"
    )

    report = await _call_openai_json(prompt)
    report["ok"] = True
    report["days"] = context["days"]
    report["start"] = context["start"]
    report["end"] = context["end"]
    report["month"] = month
    report["client_id"] = dash.get("client_id")
    report["top_words"] = top_words_from_comments
    report["comments_count"] = len(comments)
    report["media_count"] = len(media)

    if not comments:
        report["data_quality_note"] = (
            report.get("data_quality_note")
            or "Não há comentários suficientes no período para inferir sentimento/linguagem com confiança."
        )

    return report
