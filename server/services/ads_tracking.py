"""Strict UTM tracking parameters shared by Meta and Google publishing operations.

No URL rewriting and no provider-side writes until publication is confirmed.
"""
from typing import Any, Dict
from urllib.parse import urlencode

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def clean_tracking(raw: Any) -> Dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("Os parâmetros de rastreamento são inválidos.")
    cleaned: Dict[str, str] = {}
    for key in UTM_KEYS:
        value = raw.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ValueError(f"Parâmetro {key} inválido.")
        value = value.strip()
        if not value:
            continue
        if len(value) > 150 or any(char in value for char in ("\r", "\n", "\x00", "{", "}")):
            raise ValueError(f"Parâmetro {key} inválido.")
        cleaned[key] = value
    return cleaned


def tracking_suffix(cleaned: Dict[str, str]) -> str:
    return urlencode([(key, cleaned[key]) for key in UTM_KEYS if cleaned.get(key)])
