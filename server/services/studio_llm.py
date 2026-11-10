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
- Revise em silêncio: aderência à marca, especificidade, clareza e veracidade. Português do Brasil, salvo quando a regra de IDIOMA do pedido disser outro."""

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
                   images: tuple | list = (), client_id: str | None = None, leak_check: bool = True,
                   guidance: bool = True, max_output_tokens: int | None = None) -> Dict[str, Any]:
    """Resposta da IA em JSON. Com a marca conhecida (client_id ou a empresa já autorizada na requisição),
    passa pela auditoria anti-vazamento: citou outra marca da Mugô → refaz 1 vez avisando; citou de novo → bloqueia.

    ``guidance=False`` não anexa a orientação criativa (para conversas que não escrevem peças: menos tokens).
    ``max_output_tokens`` limita o tamanho da resposta."""
    cid = client_id
    if cid is None and leak_check:
        from .tenant import _REQUEST_CLIENT
        cid = _REQUEST_CLIENT.get()
    if cid is None:
        from .tenant import _REQUEST_CLIENT
        cid = _REQUEST_CLIENT.get()
    extra = {"guidance": guidance, "max_output_tokens": max_output_tokens, "client_id": cid}
    data = await _llm_json_once(instructions=instructions, prompt=prompt, schema_name=schema_name, schema=schema,
                                temperature=temperature, timeout=timeout, model=model, images=images, **extra)
    if not (leak_check and cid):
        return data
    from .brand_guard import flatten
    from .tenant_guard import find_leaks, leak_terms
    terms = await leak_terms(cid)
    found = find_leaks(flatten(data), terms) if terms else []
    if not found:
        return data
    print(f"[tenant_guard] leak schema={schema_name} client_id={cid} terms={len(found)} action=retry")
    warn = ("\n\nREGRA DE CONFIDENCIALIDADE: esta resposta é só para esta marca. NUNCA cite estas outras marcas, "
            f"que são de outros clientes da agência: {', '.join(found)}.")
    data = await _llm_json_once(instructions=instructions + warn, prompt=prompt, schema_name=schema_name, schema=schema,
                                temperature=temperature, timeout=timeout, model=model, images=images, **extra)
    again = find_leaks(flatten(data), terms)
    if again:
        print(f"[tenant_guard] leak schema={schema_name} client_id={cid} terms={len(again)} action=blocked")
        from .studio_calendar import StudioError
        raise StudioError("AI_TENANT_LEAK", "A IA citou outra marca atendida pela Mugô e a resposta foi bloqueada.")
    return data


async def _llm_json_once(*, instructions: str, prompt: str, schema_name: str, schema: Dict[str, Any],
                         temperature: float = 0.6, timeout: float = 90, model: str | None = None,
                         images: tuple | list = (), guidance: bool = True,
                         max_output_tokens: int | None = None, client_id: str | None = None) -> Dict[str, Any]:
    from .ai_summary import _extract_output_text
    from .ai_usage import track, track_response
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
        "instructions": f"{instructions}\n\n{CREATIVE_GUIDANCE}" if guidance else instructions,
        "input": user_input,
        "text": {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
    }
    if _accepts_temperature(chosen):
        payload["temperature"] = temperature
    if max_output_tokens:
        payload["max_output_tokens"] = int(max_output_tokens)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post("https://api.openai.com/v1/responses",
                                         headers={"Authorization": f"Bearer {api_key}"}, json=payload)
    except httpx.TimeoutException:
        track(feature=schema_name, model=chosen, client_id=client_id, error_code="timeout")
        raise StudioError("AI_PROVIDER_TIMEOUT") from None
    except httpx.HTTPError:
        track(feature=schema_name, model=chosen, client_id=client_id, error_code="network")
        raise StudioError("AI_PROVIDER_ERROR") from None
    track_response(response, feature=schema_name, model=chosen, client_id=client_id)
    if response.status_code >= 400:
        detail = provider_error_detail(response)
        print(f"[studio][llm] schema={schema_name} model={chosen} images={len(images)} status={response.status_code} detail={detail}")
        raise StudioError(provider_error_code(detail), detail)
    try:
        data = json.loads(_extract_output_text(response.json()))
    except (ValueError, TypeError):
        raise StudioError("AI_INVALID_OUTPUT") from None
    if not isinstance(data, dict):
        raise StudioError("AI_INVALID_OUTPUT")
    return data


def provider_error_detail(response: Any) -> str:
    """'http_429:insufficient_quota', 'http_401:invalid_api_key'… Só status e código: nunca o corpo inteiro."""
    detail = f"http_{getattr(response, 'status_code', '?')}"
    try:
        err = (response.json() or {}).get("error") or {}
        code = str(err.get("code") or err.get("type") or "").strip()[:60]
    except Exception:  # noqa: BLE001
        code = ""
    return f"{detail}:{code}" if code else detail


def provider_error_code(detail: str) -> str:
    """Traduz o erro da OpenAI num código que a tela explica (sem crédito, chave, limite por minuto...)."""
    if any(code in detail for code in ("insufficient_quota", "billing_hard_limit")):
        return "AI_PROVIDER_QUOTA"
    if detail.startswith("http_401") or "invalid_api_key" in detail:
        return "AI_PROVIDER_AUTH"
    if detail.startswith("http_429"):
        return "AI_PROVIDER_RATE"
    if detail.startswith("http_400") or detail.startswith("http_404"):
        return "AI_PROVIDER_REQUEST"
    return "AI_PROVIDER_ERROR"


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
