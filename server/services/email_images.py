"""Validate and normalize campaign images before publishing them to Storage."""
from asyncio import to_thread
from io import BytesIO
from uuid import uuid4

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from .email_marketing import EmailError
from .studio_art import signed_upload_target

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000
FORMATS = {"JPEG", "PNG", "WEBP"}


def normalize_image(data: bytes) -> tuple[bytes, str, str]:
    if len(data) > MAX_BYTES:
        raise EmailError("IMAGE_TOO_LARGE", "A imagem deve ter até 5 MB.", 413)
    try:
        with Image.open(BytesIO(data), formats=list(FORMATS)) as source:
            if source.width * source.height > MAX_PIXELS or getattr(source, "is_animated", False):
                raise EmailError("IMAGE_DIMENSIONS", "Use uma imagem estática de até 16 megapixels.", 422)
            image = ImageOps.exif_transpose(source)
            output = BytesIO()
            if source.format == "JPEG":
                image.convert("RGB").save(output, "JPEG", quality=95, icc_profile=source.info.get("icc_profile"))
                kind, extension = "image/jpeg", "jpg"
            else:
                mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
                image.convert(mode).save(output, "PNG", icc_profile=source.info.get("icc_profile"))
                kind, extension = "image/png", "png"
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise EmailError("INVALID_IMAGE", "Selecione um JPG, PNG ou WebP válido.", 422) from exc
    if output.tell() > MAX_BYTES:
        raise EmailError("IMAGE_TOO_LARGE", "A imagem preparada para o e-mail passou de 5 MB. Reduza suas dimensões.", 413)
    return output.getvalue(), kind, extension


async def upload_image(client_id: str, data: bytes) -> str:
    content, kind, extension = await to_thread(normalize_image, data)
    namespace = client_id.encode().hex()
    path = f"email-marketing/{namespace}/{uuid4().hex}.{extension}"
    target = await signed_upload_target("email-marketing-images", path, kind)
    if not target["public_url"].startswith("https://"):
        raise EmailError("STORAGE_HTTPS", "O armazenamento de e-mail precisa de HTTPS.", 503)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.put(target["upload_url"], content=content,
                                    headers={"Content-Type": kind, "x-upsert": "false"})
        response.raise_for_status()
    return target["public_url"]
