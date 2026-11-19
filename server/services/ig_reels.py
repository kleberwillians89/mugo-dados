"""Opções de publicação do Reels (capa, onde aparece, teste, áudio, primeiro comentário).

Ficam na coluna ``reels_options`` da pauta (migração 000131) e só valem para o formato Reels no Instagram:

- Capa: ``cover_mode`` "frame" manda ``thumb_offset`` (milissegundos do vídeo); "image" manda ``cover_url``
  (JPG 1080×1920 feito pela equipe). Se a Meta receber os dois, a imagem vence; aqui só um vai.
- ``share_to_feed``: só vai quando foi escolhido na tela; pauta antiga ({}) continua publicando como antes.
- ``trial``: Reels de teste, mostrado primeiro só para quem não segue. "manual" = a equipe decide no app;
  "auto" = o Instagram leva aos seguidores se performar bem (``SS_PERFORMANCE``).
- ``first_comment``: comentário da própria marca logo depois de publicar. Se falhar, o post continua publicado.
- ``music``: música (ou áudio de Reels) da biblioteca do Instagram, escolhida pela Audio API. Vai como
  ``audio_configuration`` com o volume da música e do som do vídeo. Com música, o nome do áudio original não vai.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from .studio_calendar import StudioError

MAX_OFFSET_MS = 15 * 60 * 1000  # Reels pela API: até 15 minutos
COVER_MODES = ("frame", "image")
TRIALS = {"off": None, "manual": "MANUAL", "auto": "SS_PERFORMANCE"}
_DRIVE_FILE = re.compile(r"^https://drive\.google\.com/(?:file/d/([\w-]{10,})|open\?id=([\w-]{10,})|uc\?(?:.*&)?id=([\w-]{10,}))")


def _text(value: Any, limit: int) -> Optional[str]:
    text = str(value or "").strip()
    return text[:limit] if text else None


def clean_reels_options(value: Any) -> Dict[str, Any]:
    """Normaliza o que veio da tela. Campo desconhecido é ignorado; link de capa inválido é recusado."""
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Any] = {}
    mode = value.get("cover_mode")
    if mode in COVER_MODES:
        out["cover_mode"] = mode
    offset = value.get("thumb_offset_ms")
    if offset is not None and offset != "":
        try:
            out["thumb_offset_ms"] = max(0, min(MAX_OFFSET_MS, int(float(offset))))
        except (TypeError, ValueError):
            pass
    cover = _text(value.get("cover_url"), 1000)
    if cover:
        if not re.match(r"^https://\S+$", cover):
            raise StudioError("REELS_COVER_INVALID")
        out["cover_url"] = cover
    if isinstance(value.get("share_to_feed"), bool):
        out["share_to_feed"] = value["share_to_feed"]
    if value.get("trial") in TRIALS:
        out["trial"] = value["trial"]
    for key, limit in (("audio_name", 100), ("first_comment", 2200)):
        text = _text(value.get(key), limit)
        if text:
            out[key] = text
    music = clean_music(value.get("music"))
    if music:
        out["music"] = music
    return out


def _volume(value: Any) -> int:
    try:
        return max(1, min(100, int(float(value))))
    except (TypeError, ValueError):
        return 100


def clean_music(value: Any) -> Optional[Dict[str, Any]]:
    """Música escolhida: só o ID numérico da Meta é obrigatório; título, artista e capa servem para a tela."""
    if not isinstance(value, dict):
        return None
    audio_id = str(value.get("audio_id") or "").strip()
    if not re.fullmatch(r"\d{1,40}", audio_id):
        return None
    out: Dict[str, Any] = {"audio_id": audio_id, "audio_volume": _volume(value.get("audio_volume", 100)),
                           "video_volume": _volume(value.get("video_volume", 100))}
    for key, limit in (("title", 120), ("artist", 120)):
        text = _text(value.get(key), limit)
        if text:
            out[key] = text
    cover = _text(value.get("cover"), 1000)
    if cover and cover.startswith("https://"):
        out["cover"] = cover
    return out


def _cover_link(url: str) -> Optional[str]:
    """Link direto da capa: arquivo do Drive vira download; Canva e outros formatos não servem."""
    drive = _DRIVE_FILE.match(url)
    if drive:
        return f"https://drive.google.com/uc?export=download&id={next(g for g in drive.groups() if g)}"
    path = url.split("?", 1)[0].lower()
    return url if path.endswith((".jpg", ".jpeg")) else None


def apply_reels_options(plan: Dict[str, Any], raw: Any) -> Optional[str]:
    """Põe as opções no contêiner do Reels. Devolve um aviso (capa ignorada) ou None."""
    if not plan or plan.get("type") != "reels":
        return None
    try:
        opts = clean_reels_options(raw)
    except StudioError:
        return "o link da capa do Reels não é válido; o Reels sai com o primeiro frame"
    fields = plan["fields"]
    warning = None
    if opts.get("cover_mode") == "image" and opts.get("cover_url"):
        link = _cover_link(opts["cover_url"])
        if link:
            fields["cover_url"] = link
        else:
            warning = "a capa do Reels precisa ser JPG; o Reels sai com o frame escolhido"
    if "cover_url" not in fields and opts.get("thumb_offset_ms") is not None:
        fields["thumb_offset"] = str(opts["thumb_offset_ms"])
    if "share_to_feed" in opts:
        fields["share_to_feed"] = "true" if opts["share_to_feed"] else "false"
    strategy = TRIALS.get(opts.get("trial") or "off")
    if strategy:
        fields["trial_params"] = json.dumps({"graduation_strategy": strategy})
    music = opts.get("music")
    if music:
        fields["audio_configuration"] = json.dumps({"audio_id": music["audio_id"], "audio_volume": music["audio_volume"],
                                                    "video_volume": music["video_volume"]})
    elif opts.get("audio_name"):
        fields["audio_name"] = opts["audio_name"]
    return warning


def first_comment(item: Dict[str, Any]) -> Optional[str]:
    if str(item.get("format") or "").lower() not in ("reels", "video"):
        return None
    try:
        return clean_reels_options(item.get("reels_options")).get("first_comment")
    except StudioError:
        return None
