"""Mídia kit e valores de cada criador, por empresa (migração 000144).

Um registro por (empresa, criador): arquivos do mídia kit (enviados ao Storage ou link https),
preços por entregável, contato e observações. Os valores são da empresa: tudo filtra por client_id.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select, sb_upsert
from .studio_calendar import StudioError

TABLE = "creator_media_kits"
KIT_TYPES = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_FILES = 10
MAX_PRICES = 30
MAX_DEALS = 100
# CRM de criadores (migração 000145): onde está a negociação com cada criador.
STATUSES = ("novo", "contatado", "negociando", "fechado", "nao_fechou")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _text(value: Any, limit: int) -> Optional[str]:
    text = str(value or "").strip()[:limit]
    return text or None


def clean_prices(value: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in value if isinstance(value, list) else []:
        if not isinstance(row, dict):
            continue
        deliverable = _text(row.get("deliverable"), 120)
        if not deliverable:
            continue
        try:
            amount = round(float(row["amount"]), 2) if row.get("amount") not in (None, "") else None
        except (TypeError, ValueError):
            amount = None
        if amount is not None and (amount < 0 or amount > 10_000_000):
            amount = None
        out.append({"deliverable": deliverable, "amount": amount, "notes": _text(row.get("notes"), 300)})
    return out[:MAX_PRICES]


def clean_files(value: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in value if isinstance(value, list) else []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url.startswith("https://") or len(url) > 1000:
            continue
        out.append({"url": url, "name": _text(row.get("name"), 160) or "Mídia kit", "kind": _text(row.get("kind"), 40) or "link",
                    "uploaded_at": _text(row.get("uploaded_at"), 40) or datetime.now(timezone.utc).isoformat()})
    return out[:MAX_FILES]


def clean_email(value: Any) -> Optional[str]:
    text = _text(value, 200)
    if text and not _EMAIL.match(text):
        raise StudioError("MEDIA_KIT_EMAIL_INVALID", "E-mail inválido.")
    return text.lower() if text else None


def clean_phone(value: Any) -> Optional[str]:
    text = _text(value, 40)
    if text and len(re.sub(r"\D", "", text)) < 8:
        raise StudioError("MEDIA_KIT_PHONE_INVALID", "Telefone inválido.")
    return text


def clean_deals(value: Any) -> List[Dict[str, Any]]:
    """Histórico de fechamentos: nunca some sozinho; a tela só acrescenta (ou a equipe apaga um por um)."""
    out: List[Dict[str, Any]] = []
    for row in value if isinstance(value, list) else []:
        if not isinstance(row, dict):
            continue
        what = _text(row.get("what"), 300)
        date = str(row.get("closed_at") or "")[:10]
        if not what or not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        try:
            amount = round(float(row["amount"]), 2) if row.get("amount") not in (None, "") else None
        except (TypeError, ValueError):
            amount = None
        if amount is not None and (amount < 0 or amount > 10_000_000):
            amount = None
        out.append({"id": _text(row.get("id"), 40) or uuid.uuid4().hex[:12], "closed_at": date, "what": what, "amount": amount,
                    "notes": _text(row.get("notes"), 500), "closed_by": _text(row.get("closed_by"), 80)})
    return out[:MAX_DEALS]


async def list_kits(client_id: str, only_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    rows = await sb_select(TABLE, select="creator_id,files,prices,email,phone,contact,deals,notes,status,status_note,status_at,updated_at", limit=500,
                           filters={"client_id": f"eq.{client_id}"}, order="updated_at.desc")
    return [r for r in rows or [] if only_ids is None or str(r.get("creator_id")) in only_ids]


def clean_status(value: Any, deals: List[Dict[str, Any]]) -> str:
    status = str(value or "").strip()
    if status and status not in STATUSES:
        raise StudioError("MEDIA_KIT_STATUS_INVALID", "Status inválido.")
    return status or ("fechado" if deals else "novo")


async def save_kit(client_id: str, creator_id: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    deals = clean_deals(data.get("deals"))
    status = clean_status(data.get("status"), deals)
    now = datetime.now(timezone.utc).isoformat()
    # A data do status só muda quando o status muda (é o "desde quando" do CRM).
    previous = await sb_select(TABLE, select="status,status_at", limit=1,
                               filters={"client_id": f"eq.{client_id}", "creator_id": f"eq.{creator_id}"})
    before = (previous or [{}])[0]
    status_at = before.get("status_at") if before.get("status") == status and before.get("status_at") else now
    row = {"client_id": client_id, "creator_id": creator_id, "files": clean_files(data.get("files")),
           "status": status, "status_note": _text(data.get("status_note"), 500), "status_at": status_at,
           "prices": clean_prices(data.get("prices")), "email": clean_email(data.get("email")), "phone": clean_phone(data.get("phone")),
           "contact": _text(data.get("contact"), 300), "deals": deals,
           "notes": _text(data.get("notes"), 4000), "updated_by": user_id, "updated_at": now}
    await sb_upsert(TABLE, [row], on_conflict="client_id,creator_id")
    return row


async def upload_target(client_id: str, content_type: str) -> Dict[str, str]:
    """Link assinado (2 h, 1 arquivo) para o mídia kit ir direto do navegador ao Storage."""
    import httpx
    kind = str(content_type or "").lower()
    ext = KIT_TYPES.get(kind)
    if not ext:
        raise StudioError("MEDIA_KIT_TYPE_INVALID", "Envie PDF, PNG, JPG ou WEBP.")
    bucket = (os.getenv("IG_MEDIA_BUCKET") or "ig-media").strip()
    path = f"creator-kits/{re.sub(r'[^a-zA-Z0-9_-]', '', client_id)[:80]}/{uuid.uuid4().hex}.{ext}"
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        raise StudioError("STORAGE_NOT_CONFIGURED")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{base}/storage/v1/object/upload/sign/{bucket}/{path}",
                                     headers={"Authorization": f"Bearer {key}", "apikey": key}, json={"expiresIn": 7200})
    signed = str((response.json() or {}).get("url") or "") if response.status_code < 400 else ""
    if not signed:
        raise StudioError("STORAGE_UPLOAD_FAILED")
    return {"upload_url": f"{base}/storage/v1{signed}" if signed.startswith("/") else signed,
            "public_url": f"{base}/storage/v1/object/public/{bucket}/{path}", "content_type": kind}
