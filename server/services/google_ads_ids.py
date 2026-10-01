from __future__ import annotations

import re
from typing import Any

_CUSTOMER_ID_RE = re.compile(r"^\d{10}$")


def normalize_google_ads_customer_id(value: Any) -> str | None:
    """
    Representação canônica interna de um customer ID do Google Ads: 10 dígitos,
    sem hífens e sem prefixo ("1234567890").

    Aceita "1234567890", "123-456-7890" e o resource name "customers/1234567890".
    Qualquer outra forma (inclusive "customers/customers/...") é inválida e
    retorna None — nunca é "consertada" para não persistir lixo.
    """
    text = str(value if value is not None else "").strip()
    if text.startswith("customers/"):
        text = text[len("customers/"):]
    text = text.replace("-", "").replace(" ", "")
    return text if _CUSTOMER_ID_RE.fullmatch(text) else None


def format_google_ads_customer_id(customer_id: str) -> str:
    """Somente exibição: 1234567890 -> 123-456-7890."""
    normalized = normalize_google_ads_customer_id(customer_id)
    if not normalized:
        return str(customer_id or "")
    return f"{normalized[:3]}-{normalized[3:6]}-{normalized[6:]}"
