"""Vídeo dentro de carrossel (imagem + vídeo no mesmo post), no padrão que a Meta aceita.

A Meta aceita carrossel misto, mas o vídeo de carrossel tem regras próprias, mais duras que as do Reels:
proporção entre 4:5 e 16:9 (vídeo vertical 9:16 de celular é recusado com "formato incompatível"), até 60 s,
no mínimo 3 s, até 1920 px de largura, H.264/HEVC e o índice (moov) no começo do arquivo.

Aqui, antes de publicar:
1. Link do Drive num slide: descobre se é vídeo ou imagem pelo próprio arquivo (antes ia sempre como imagem).
2. Cada vídeo do carrossel vira um MP4 H.264/AAC na proporção do 1º slide (o Instagram enquadra o carrossel
   pelo 1º slide), sem cortar a cena: o que sobra vira fundo desfocado do próprio vídeo. Até 60 s, 30 fps,
   faststart. A cópia vai para o Storage público do MUGOVERSO; o arquivo original não muda.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from io import BytesIO
from typing import Any, Dict, Optional

import httpx

from .studio_calendar import StudioError

MAX_VIDEO_BYTES = 300 * 1024 * 1024
MAX_SECONDS = 60
MIN_SECONDS = 3
WIDTH = 1080
DEFAULT_RATIO = 4 / 5  # retrato do feed
MIN_RATIO, MAX_RATIO = 4 / 5, 16 / 9


def ffmpeg_exe() -> Optional[str]:
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return shutil.which("ffmpeg")


async def resolve_drive_children(plan: Dict[str, Any]) -> None:
    """Slide do carrossel com link do Drive: vídeo vira slide de vídeo (antes ia como imagem e a Meta recusava)."""
    if plan.get("type") != "carousel":
        return
    for child in plan.get("children", []):
        url = child.get("image_url") or ""
        if "drive.google.com" not in url:
            continue
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    kind = (response.headers.get("content-type") or "").lower()
        except httpx.HTTPError:
            continue  # sem resposta: segue como estava e a Meta diz o que houve
        if kind.startswith("video/"):
            child.pop("image_url", None)
            child["video_url"] = url
            child["media_type"] = "VIDEO"


def frame_size(ratio: float) -> tuple[int, int]:
    ratio = min(MAX_RATIO, max(MIN_RATIO, ratio or DEFAULT_RATIO))
    height = int(round(WIDTH / ratio / 2) * 2)
    return WIDTH, height


def ffmpeg_args(exe: str, src: str, dst: str, width: int, height: int) -> list[str]:
    # Cena inteira no centro; o espaço que sobrar vira o próprio vídeo ampliado e desfocado (nada é cortado).
    graph = (f"[0:v]split=2[a][b];"
             f"[a]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=20:2[bg];"
             f"[b]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30,format=yuv420p[v]")
    return [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-t", str(MAX_SECONDS),
            "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-b:v", "5M", "-maxrate", "6M", "-bufsize", "10M",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", dst]


def duration_seconds(exe: str, src: str) -> Optional[float]:
    probe = subprocess.run([exe, "-hide_banner", "-i", src], capture_output=True, text=True, timeout=60)
    found = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr or "")
    if not found:
        return None
    h, m, s = found.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def _transcode(exe: str, data: bytes, width: int, height: int) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in"), os.path.join(tmp, "out.mp4")
        with open(src, "wb") as handle:
            handle.write(data)
        seconds = duration_seconds(exe, src)
        if seconds is not None and seconds < MIN_SECONDS:
            raise StudioError("IG_PUBLISH_FAILED", "Vídeo do carrossel precisa ter pelo menos 3 segundos.")
        done = subprocess.run(ffmpeg_args(exe, src, dst, width, height), capture_output=True, text=True, timeout=600)
        if done.returncode != 0 or not os.path.exists(dst):
            print(f"[ig_carousel_video] ffmpeg_failed code={done.returncode} err={(done.stderr or '')[-200:]!r}")
            raise StudioError("IG_PUBLISH_FAILED", "Não consegui preparar o vídeo do carrossel. Envie o vídeo em MP4 e tente de novo.")
        with open(dst, "rb") as handle:
            return handle.read()


async def _download(url: str, limit: int) -> bytes:
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        got = await client.get(url)
    if got.status_code >= 400 or not got.content:
        raise StudioError("IG_PUBLISH_FAILED", "Não consegui baixar o vídeo do carrossel. Confira se o link está público.")
    if len(got.content) > limit:
        raise StudioError("IG_PUBLISH_FAILED", "Vídeo do carrossel maior que 300 MB: envie uma versão menor.")
    return got.content


async def _first_slide_ratio(plan: Dict[str, Any]) -> float:
    """Proporção do 1º slide (o Instagram enquadra o carrossel por ele). Sem conseguir ler: 4:5."""
    children = plan.get("children") or []
    first = children[0] if children else {}
    url = first.get("image_url")
    if not url:
        return DEFAULT_RATIO
    try:
        from PIL import Image
        data = await _download(url, 40 * 1024 * 1024)
        width, height = Image.open(BytesIO(data)).size
        return width / height if height else DEFAULT_RATIO
    except Exception:  # noqa: BLE001
        return DEFAULT_RATIO


async def ensure_carousel_videos(plan: Dict[str, Any], client_id: str) -> int:
    """Converte os vídeos do carrossel para o padrão da Meta e troca o link no plano. Devolve quantos converteu."""
    if plan.get("type") != "carousel":
        return 0
    videos = [c for c in plan.get("children", []) if c.get("video_url")]
    if not videos:
        return 0
    exe = ffmpeg_exe()
    if not exe:
        print("[ig_carousel_video] ffmpeg_unavailable: vídeo segue como enviado")
        return 0
    from .ig_supabase import sb_upload_public
    width, height = frame_size(await _first_slide_ratio(plan))
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", client_id)[:80]
    done = 0
    for child in videos:
        url = child["video_url"]
        data = await _download(url, MAX_VIDEO_BYTES)
        mp4 = await asyncio.to_thread(_transcode, exe, data, width, height)
        key = hashlib.sha1(f"{url}:{width}x{height}".encode()).hexdigest()[:20]
        try:
            child["video_url"] = await sb_upload_public(f"ig-publish/{safe}/{key}.mp4", mp4, "video/mp4")
        except Exception as exc:  # noqa: BLE001 — falha de Storage vira erro legível (a pauta não fica travada)
            print(f"[ig_carousel_video] upload_failed error_type={type(exc).__name__}")
            raise StudioError("IG_PUBLISH_FAILED", "Não consegui guardar o vídeo convertido do carrossel. Tente de novo.") from None
        child["media_type"] = "VIDEO"
        done += 1
    return done
