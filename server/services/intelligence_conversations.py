"""Owner-scoped conversation metadata. No model calls or new persistence schema."""
from datetime import datetime, timezone
from .ig_supabase import sb_select, sb_update, sb_delete, sb_insert

FIELDS = "id,client_id,user_id,title,created_at,updated_at"


def _scope(client_id, user_id, conversation_id=None):
    if not client_id or not user_id or (conversation_id is not None and not str(conversation_id).strip()):
        raise RuntimeError("CONVERSATION_NOT_FOUND")
    return {"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}",
            **({"id": f"eq.{conversation_id}"} if conversation_id else {})}


def _target_scope(client_id, user_id, conversation_id):
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise RuntimeError("CONVERSATION_NOT_FOUND")
    return _scope(client_id, user_id, conversation_id)


def _owned(rows, client_id, user_id):
    return [row for row in rows if row.get("client_id") == client_id and row.get("user_id") == user_id]


async def list_conversations(client_id, user_id, limit=25, offset=0):
    size = max(1, min(int(limit), 25))
    rows = await sb_select("ai_conversations", select=FIELDS, filters=_scope(client_id, user_id),
                           order="updated_at.desc,id.desc", limit=size + 1, offset=max(0, min(int(offset), 10000)))
    rows = _owned(rows, client_id, user_id)
    return {"ok": True, "items": rows[:size], "has_more": len(rows) > size}


async def rename_conversation(client_id, user_id, conversation_id, title):
    clean = str(title or "").strip()
    if not clean or len(clean) > 120:
        raise RuntimeError("CONVERSATION_TITLE_INVALID")
    rows = await sb_update("ai_conversations", filters=_target_scope(client_id, user_id, conversation_id), patch={"title": clean})
    owned = [row for row in _owned(rows, client_id, user_id) if row.get("id") == conversation_id]
    if not owned:
        raise RuntimeError("CONVERSATION_NOT_FOUND")
    return {"ok": True, "conversation": {key: owned[0].get(key) for key in FIELDS.split(",")}}


async def delete_conversation(client_id, user_id, conversation_id):
    # Existing FK ai_messages.conversation_id ON DELETE CASCADE removes messages.
    rows = await sb_delete("ai_conversations", filters=_target_scope(client_id, user_id, conversation_id))
    if not any(row.get("id") == conversation_id for row in _owned(rows, client_id, user_id)):
        raise RuntimeError("CONVERSATION_NOT_FOUND")
    return {"ok": True}


async def create_conversation(client_id, user_id):
    _scope(client_id, user_id)
    row = await sb_insert("ai_conversations", {"client_id": client_id, "user_id": user_id, "title": "Nova conversa"})
    if not row or not row.get("id") or not _owned([row], client_id, user_id):
        raise RuntimeError("CONVERSATION_CREATE_FAILED")
    return {"ok": True, "conversation": {key: row.get(key) for key in FIELDS.split(",")}}


async def resume_conversation(client_id, user_id, conversation_id):
    rows = await sb_update("ai_conversations", filters=_target_scope(client_id, user_id, conversation_id),
                           patch={"updated_at": datetime.now(timezone.utc).isoformat()})
    if not any(row.get("id") == conversation_id for row in _owned(rows, client_id, user_id)):
        raise RuntimeError("CONVERSATION_NOT_FOUND")
    return {"ok": True}
