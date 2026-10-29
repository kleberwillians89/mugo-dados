"""Chamada à OpenAI com saída JSON validada por schema, comum a todos os motores do Studio.

Mesma chave e mesmo modelo da Inteligência (OPENAI_API_KEY / OPENAI_MODEL).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

import httpx

# Orientação criativa trazida do iAgência (creative_guidance + "regras de ouro"),
# aplicada a todo texto gerado pelo Studio.
CREATIVE_GUIDANCE = """ORIENTAÇÃO CRIATIVA (vale para tudo que você escrever):
- Parta dos DADOS da marca: o que já performou, o que o cliente aprovou, o que ele pediu para mudar, campanhas que venderam e metas do mês.
- Respeite a voz da marca. Humor, emoção e linguagem popular só quando o perfil permitir.
- Busque uma observação concreta sobre o público e ligue a um diferencial real do produto ou da marca.
- Prefira detalhes específicos e frases curtas (parágrafos de até 3 linhas). Nada que sirva para qualquer concorrente.
- Proibido clichê: "alavancar", "jornada", "transformar", "descubra o segredo", "fique por dentro", "não perca", "imperdível".
- Não invente benefícios, números, preços, depoimentos, garantias, urgência nem promoções que não estejam nos dados.
- Repita o que o cliente aprovou como REFERÊNCIA de tom, nunca como cópia; evite o que ele pediu para ajustar.
- Varie abertura, argumento e CTA entre peças.
- Revise em silêncio: aderência à marca, especificidade, clareza e veracidade. Português do Brasil."""

BANNED_CLICHES = ("alavancar", "jornada", "transformar", "descubra o segredo", "fique por dentro", "não perca", "imperdível")


async def llm_json(*, instructions: str, prompt: str, schema_name: str, schema: Dict[str, Any],
                   temperature: float = 0.6, timeout: float = 90) -> Dict[str, Any]:
    from .ai_summary import _extract_output_text
    from .studio_calendar import StudioError

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise StudioError("AI_PROVIDER_NOT_CONFIGURED")
    payload = {
        "model": (os.getenv("OPENAI_MODEL") or "gpt-4.1-mini").strip(),
        "instructions": f"{instructions}\n\n{CREATIVE_GUIDANCE}",
        "input": prompt,
        "temperature": temperature,
        "text": {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post("https://api.openai.com/v1/responses",
                                         headers={"Authorization": f"Bearer {api_key}"}, json=payload)
    except httpx.TimeoutException:
        raise StudioError("AI_PROVIDER_TIMEOUT") from None
    except httpx.HTTPError:
        raise StudioError("AI_PROVIDER_ERROR") from None
    if response.status_code >= 400:
        print(f"[studio][llm] schema={schema_name} status={response.status_code}")
        raise StudioError("AI_PROVIDER_ERROR")
    try:
        data = json.loads(_extract_output_text(response.json()))
    except (ValueError, TypeError):
        raise StudioError("AI_INVALID_OUTPUT") from None
    if not isinstance(data, dict):
        raise StudioError("AI_INVALID_OUTPUT")
    return data


def obj(properties: Dict[str, Any]) -> Dict[str, Any]:
    """Schema estrito: todos os campos obrigatórios, nada além deles."""
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


STR = {"type": "string"}
INT = {"type": "integer"}
NUM = {"type": "number"}


def arr(items: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "array", "items": items}


def flag_words(text: str, extra: tuple | list = ()) -> list[str]:
    low = (text or "").lower()
    return sorted({w for w in (*BANNED_CLICHES, *(x.lower() for x in extra if x)) if w and w in low})
