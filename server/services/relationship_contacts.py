"""Base de Relacionamento a partir dos clientes já sincronizados por e-commerce.

Não faz scraping nem reimporta pedidos. Cada fonte continua sendo a verdade;
esta projeção criptografada é atualizada por tenant e não concede opt-in.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from .commerce_context import FBITS, SHOPIFY, resolve_commerce_provider
from .crypto import encrypt_secret
from .email_marketing import valid_email
from .ig_supabase import sb_select, sb_upsert
from .sales_by_origin import _paged

TABLE = "relationship_contacts"
LIMIT = 20000
BATCH = 200


class ContactSyncError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def _key(client_id: str, provider: str, external: str) -> str:
    return hashlib.sha256(f"{client_id}|{provider}|{external}".encode()).hexdigest()


def _clean(value, length=250) -> str:
    return str(value or "").strip()[:length]


def _row(client_id: str, provider: str, item: dict) -> dict | None:
    external = _clean(item.get("shopify_customer_id") if provider == SHOPIFY else item.get("fbits_customer_id"))
    mail = valid_email(item.get("email"))
    phone = "".join(c for c in _clean(item.get("phone"), 40) if c.isdigit())
    phone = phone if 10 <= len(phone) <= 15 else ""
    if not (external or mail or phone):
        return None
    identity = external or (f"email:{mail}" if mail else f"phone:{phone}")
    name = (" ".join(x for x in [_clean(item.get("first_name"), 100), _clean(item.get("last_name"), 100)] if x)
            if provider == SHOPIFY else _clean(item.get("name"), 200))
    return {
        "client_id": client_id,
        "provider": provider,
        "identity_hash": _key(client_id, provider, identity),
        "external_id": external or None,
        "email_hash": hashlib.sha256(f"mugo-mail:{mail}".encode()).hexdigest()[:32] if mail else None,
        "phone_hash": hashlib.sha256(f"mugo-phone:{phone}".encode()).hexdigest() if phone else None,
        "name_ciphertext": encrypt_secret(name) if name else None,
        "email_ciphertext": encrypt_secret(mail) if mail else None,
        "phone_ciphertext": encrypt_secret(phone) if phone else None,
        # Omitir flags: defaults do banco são false para novos registros;
        # upserts não sobrescrevem consentimentos verificados preexistentes.
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }


async def sync_existing_customers(client_id: str) -> dict:
    """Projeção da base já gravada, sem importar novas fontes nem criar consentimento."""
    resolution = await resolve_commerce_provider(client_id)
    provider = str(resolution.get("provider") or "").lower()
    if provider not in (SHOPIFY, FBITS):
        raise ContactSyncError("Empresa sem e-commerce conectado. CRM externo precisa de adaptador próprio.", 409)
    table = "shopify_customers" if provider == SHOPIFY else "fbits_customers"
    order = "updated_at_shopify.desc" if provider == SHOPIFY else "synced_at.desc"
    rows, truncated = await _paged(table, select="*", filters={"client_id": f"eq.{client_id}"}, order=order, max_rows=LIMIT)
    if truncated:
        raise ContactSyncError("Base com 20 mil registros ou mais: aumente a janela de importação antes de executar.", 409)
    data = {}
    for item in rows:
        if str(item.get("client_id") or "") != client_id:
            continue
        prepared = _row(client_id, provider, item)
        if prepared:
            data[prepared["identity_hash"]] = prepared
    values = list(data.values())
    for start in range(0, len(values), BATCH):
        await sb_upsert(TABLE, values[start:start + BATCH], on_conflict="client_id,provider,identity_hash")
    return {"provider": provider, "source_records": len(rows), "contacts_synchronized": len(values),
            "eligible_for_marketing": 0, "note": "Consentimento não inferido por cadastro ou compra."}


async def contacts_status(client_id: str) -> dict:
    """Resumo sem PII, limitado ao tenant."""
    rows, truncated = await _paged(TABLE, select="provider,identity_hash,last_synced_at", filters={
        "client_id": f"eq.{client_id}"}, order="last_synced_at.desc", max_rows=LIMIT)
    return {"total": len(rows), "truncated": truncated,
            "by_provider": {provider: sum(1 for r in rows if r.get("provider") == provider)
                            for provider in sorted({str(r.get("provider") or "") for r in rows})},
            "last_synced_at": rows[0].get("last_synced_at") if rows else None}


async def project_updated_customers(client_id: str, provider: str, items: list[dict]) -> None:
    """Atualização incremental após sync nativo; nunca interrompe o conector.

    Desligada por padrão até revisar exclusões/retificação e validar a migração.
    """
    if (os.getenv("RELATIONSHIP_AUTO_PROJECT_ENABLED") or "").lower() != "true":
        return
    if provider not in (SHOPIFY, FBITS):
        return
    data = {}
    for item in items:
        if str(item.get("client_id") or "") != client_id:
            continue
        projected = _row(client_id, provider, item)
        if projected:
            data[projected["identity_hash"]] = projected
    values = list(data.values())
    try:
        for start in range(0, len(values), BATCH):
            await sb_upsert(TABLE, values[start:start + BATCH], on_conflict="client_id,provider,identity_hash")
    except Exception as exc:
        # Sync da loja é a fonte primária: não falhar por causa de projeção derivada.
        print(f"[relationship_contacts] provider={provider} status=incremental_error error_type={type(exc).__name__}")


async def sync_whatsapp_conversations(client_id: str, *, days: int = 365) -> dict:
    """Converte conversas históricas em perfis identificados apenas pela phone_key.

    O CRM/WhatsApp continua sendo a fonte de verdade: não copia mensagens,
    não tenta recuperar telefone mascarado e não presume consentimento.
    """
    from datetime import timedelta
    from .whatsapp_sources import brand_leads
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=max(1, min(days, 3650)))).date().isoformat()
    result = await brand_leads(client_id, since, now.date().isoformat())
    if not result.get("available"):
        raise ContactSyncError("Fonte WhatsApp não disponível para esta empresa.", 409)
    if result.get("truncated"):
        raise ContactSyncError("Histórico WhatsApp incompleto; sincronização paginada necessária.", 409)
    leads = result.get("leads") or []
    data = {}
    for lead in leads:
        key = _clean(lead.get("phone_key"), 120)
        if not key or len(key) < 16 or not all(ch in "0123456789abcdefABCDEF" for ch in key):
            continue
        identity = _key(client_id, "whatsapp", key)
        data[identity] = {
            "client_id": client_id, "provider": "whatsapp",
            "identity_hash": identity, "external_id": None,
            "email_hash": None, "phone_hash": None,
            "name_ciphertext": None, "email_ciphertext": None,
            "phone_ciphertext": None,
            # Consentimentos existentes são preservados no upsert.
            "last_synced_at": now.isoformat(),
        }
    values = list(data.values())
    for start in range(0, len(values), BATCH):
        await sb_upsert(TABLE, values[start:start + BATCH], on_conflict="client_id,provider,identity_hash")
    return {"provider": "whatsapp", "source_records": len(leads),
            "contacts_synchronized": len(values), "eligible_for_marketing": 0,
            "note": "Chaves de conversa, sem número em claro e sem opt-in presumido."}


# ------------------------------------------------------------------ planilha (Excel ou CSV) para o Disparo em massa

SHEET = "planilha"
SHEET_MAX_BYTES = 10 * 1024 * 1024
SHEET_MAX_ROWS = LIMIT
_PHONE_HEADERS = ("telefone", "celular", "whatsapp", "whats", "fone", "phone", "mobile", "numero", "número", "tel")
_NAME_HEADERS = ("nome", "name", "cliente", "primeiro nome", "first name", "first_name")
_EMAIL_HEADERS = ("email", "e-mail", "mail")


def _norm(text) -> str:
    import unicodedata
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(plain.replace("_", " ").replace("-", " ").split())


def _pick(headers: list, wanted: tuple) -> int | None:
    norm = [_norm(h) for h in headers]
    for want in wanted:  # igual primeiro, depois "contém" (ex.: "Telefone celular")
        w = _norm(want)
        if w in norm:
            return norm.index(w)
    for want in wanted:
        w = _norm(want)
        for i, h in enumerate(norm):
            if w and w in h.split() or (len(w) > 4 and w in h):
                return i
    return None


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():  # Excel guarda telefone como número: 11999998888.0
        return str(int(value))
    return str(value).strip()


def read_sheet(filename: str, raw: bytes) -> list[list[str]]:
    """Linhas (com o cabeçalho) de um .xlsx ou .csv. Puro, para teste."""
    name = (filename or "").lower()
    if len(raw) > SHEET_MAX_BYTES:
        raise ContactSyncError("Planilha acima de 10 MB. Divida em partes.", 413)
    if name.endswith((".xlsx", ".xlsm")):
        import io
        from openpyxl import load_workbook
        try:
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception:  # noqa: BLE001
            raise ContactSyncError("Não consegui abrir a planilha. Salve como .xlsx ou .csv e tente de novo.", 422) from None
        sheet = book.worksheets[0]
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append([_cell(v) for v in row])
            if len(rows) > SHEET_MAX_ROWS + 1:
                break
        book.close()
        return rows
    if name.endswith((".csv", ".txt")):
        import csv
        import io
        text = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        sample = (text or "")[:4096]
        delimiter = ";" if sample.count(";") > sample.count(",") else ("\t" if sample.count("\t") > sample.count(",") else ",")
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text or ""), delimiter=delimiter)][:SHEET_MAX_ROWS + 1]
    if name.endswith(".xls"):
        raise ContactSyncError("Formato .xls antigo: abra no Excel e salve como .xlsx ou .csv.", 422)
    raise ContactSyncError("Envie uma planilha .xlsx ou .csv.", 422)


def sheet_contacts(rows: list[list[str]]) -> dict:
    """Cabeçalho → colunas de telefone, nome e e-mail; linhas → contatos válidos, sem repetir. Puro, para teste."""
    from .whatsapp_campaign_send import normalize_phone
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise ContactSyncError("A planilha está vazia.", 422)
    header = rows[0]
    phone_col = _pick(header, _PHONE_HEADERS)
    if phone_col is None:
        raise ContactSyncError("Não achei a coluna de telefone. Use um cabeçalho como Telefone, Celular ou WhatsApp.", 422)
    name_col, email_col = _pick(header, _NAME_HEADERS), _pick(header, _EMAIL_HEADERS)
    contacts: dict[str, dict] = {}
    invalid = 0
    for row in rows[1:SHEET_MAX_ROWS + 1]:
        cell = lambda i: row[i] if i is not None and i < len(row) else ""  # noqa: E731
        phone = normalize_phone(cell(phone_col))
        if not phone:
            invalid += 1
            continue
        contacts.setdefault(phone, {"phone": phone, "name": _clean(cell(name_col), 200), "email": cell(email_col)})
    return {"contacts": list(contacts.values()), "invalid": invalid, "rows": max(0, len(rows) - 1),
            "columns": {"telefone": header[phone_col], "nome": header[name_col] if name_col is not None else None,
                        "email": header[email_col] if email_col is not None else None}}


async def import_sheet(client_id: str, *, filename: str, raw: bytes, replace: bool = False) -> dict:
    """Leads da planilha entram como origem "planilha" (criptografados, como os outros). Não presume consentimento:
    quem importa confirma na tela que esses contatos aceitaram receber mensagens da marca."""
    from .ig_supabase import sb_delete
    parsed = sheet_contacts(read_sheet(filename, raw))
    if not parsed["contacts"]:
        raise ContactSyncError("Nenhum telefone válido na planilha (use DDD + número).", 422)
    if replace:
        await sb_delete(TABLE, filters={"client_id": f"eq.{client_id}", "provider": f"eq.{SHEET}"})
    now = datetime.now(timezone.utc).isoformat()
    values = []
    for c in parsed["contacts"]:
        mail = valid_email(c.get("email"))
        values.append({
            "client_id": client_id, "provider": SHEET, "identity_hash": _key(client_id, SHEET, f"phone:{c['phone']}"),
            "external_id": None,
            "email_hash": hashlib.sha256(f"mugo-mail:{mail}".encode()).hexdigest()[:32] if mail else None,
            "phone_hash": hashlib.sha256(f"mugo-phone:{c['phone']}".encode()).hexdigest(),
            "name_ciphertext": encrypt_secret(c["name"]) if c.get("name") else None,
            "email_ciphertext": encrypt_secret(mail) if mail else None,
            "phone_ciphertext": encrypt_secret(c["phone"]),
            "last_synced_at": now,
        })
    for start in range(0, len(values), BATCH):
        await sb_upsert(TABLE, values[start:start + BATCH], on_conflict="client_id,provider,identity_hash")
    return {"provider": SHEET, "rows": parsed["rows"], "contacts_imported": len(values), "invalid": parsed["invalid"],
            "columns": parsed["columns"], "replaced": replace}


def mask_phone(digits: str) -> str:
    """5511999998888 → +55 11 9••••-8888 (o bastante para reconhecer, sem expor o número inteiro). Puro, para teste."""
    d = "".join(c for c in str(digits or "") if c.isdigit())
    if len(d) < 8:
        return "••••"
    country, rest = (d[:2], d[2:]) if d.startswith("55") and len(d) >= 12 else ("", d)
    area, local = (rest[:2], rest[2:]) if len(rest) >= 10 else ("", rest)
    return " ".join(x for x in (f"+{country}" if country else "", area, f"{local[:1]}••••-{local[-4:]}") if x)


async def sheet_contacts_list(client_id: str, *, q: str = "", limit: int = 500) -> dict:
    """Contatos da planilha para escolher quem recebe (nome e telefone mascarado). Busca por nome ou fim do número."""
    from .crypto import decrypt_secret
    rows, truncated = await _paged(TABLE, select="identity_hash,name_ciphertext,phone_ciphertext", filters={
        "client_id": f"eq.{client_id}", "provider": f"eq.{SHEET}"}, order="identity_hash.asc", max_rows=LIMIT)

    def plain(value) -> str:
        try:
            return decrypt_secret(value) if value else ""
        except Exception:  # noqa: BLE001
            return ""
    needle = _norm(q)
    digits = "".join(c for c in q if c.isdigit())
    out = []
    for r in rows:
        name, phone = plain(r.get("name_ciphertext")), plain(r.get("phone_ciphertext"))
        if needle and not ((needle in _norm(name)) or (digits and phone.endswith(digits))):
            continue
        out.append({"id": r["identity_hash"], "name": name or "Sem nome", "phone": mask_phone(phone)})
    out.sort(key=lambda c: _norm(c["name"]))
    return {"total": len(rows), "matches": len(out), "contacts": out[:max(1, min(limit, 2000))], "truncated": truncated}
