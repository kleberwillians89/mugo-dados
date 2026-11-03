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


def profile_model() -> str:
    """Modelo mais forte só para o perfil da marca (roda pouco: no botão e uma vez por mês)."""
    return (os.getenv("OPENAI_PROFILE_MODEL") or "gpt-4.1").strip()


def _accepts_temperature(model: str) -> bool:
    # Modelos de raciocínio (o1/o3/o4, gpt-5) não aceitam temperature.
    low = model.lower()
    return not (low.startswith(("o1", "o3", "o4", "gpt-5")))


async def llm_json(*, instructions: str, prompt: str, schema_name: str, schema: Dict[str, Any],
                   temperature: float = 0.6, timeout: float = 90, model: str | None = None,
                   images: tuple | list = ()) -> Dict[str, Any]:
    from .ai_summary import _extract_output_text
    from .studio_calendar import StudioError

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise StudioError("AI_PROVIDER_NOT_CONFIGURED")
    chosen = (model or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini").strip()
    # Imagens (data URLs já baixadas por nós) vão junto do texto, na mesma mensagem.
    user_input: Any = prompt
    if images:
        user_input = [{"role": "user", "content": [{"type": "input_text", "text": prompt},
                                                   *({"type": "input_image", "image_url": url, "detail": "low"} for url in images)]}]
    payload: Dict[str, Any] = {
        "model": chosen,
        "instructions": f"{instructions}\n\n{CREATIVE_GUIDANCE}",
        "input": user_input,
        "text": {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
    }
    if _accepts_temperature(chosen):
        payload["temperature"] = temperature
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post("https://api.openai.com/v1/responses",
                                         headers={"Authorization": f"Bearer {api_key}"}, json=payload)
    except httpx.TimeoutException:
        raise StudioError("AI_PROVIDER_TIMEOUT") from None
    except httpx.HTTPError:
        raise StudioError("AI_PROVIDER_ERROR") from None
    if response.status_code >= 400:
        print(f"[studio][llm] schema={schema_name} model={chosen} images={len(images)} status={response.status_code}")
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
