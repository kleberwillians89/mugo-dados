"""Benchmarking automático de preços: lê o preço público de páginas de produto (concorrentes e a própria marca)
uma vez por dia e guarda o histórico.

Como o preço é lido, em ordem:
1. loja Shopify: ``/products/<handle>.js`` (JSON público da própria loja; preço em centavos, variantes, disponível);
2. qualquer loja: dado estruturado ``application/ld+json`` do tipo Product (o mesmo que o Google lê);
3. meta tag ``product:price:amount``.
Sem preço legível, fica registrado o motivo; nada é estimado.

Segurança: só https, só endereço público (bloqueia IP privado/local), resposta até 3 MB, 15 s de limite.

Anúncios: a API oficial da Biblioteca de Anúncios da Meta só devolve anúncios comerciais que rodaram na UE;
fora dela, só anúncios políticos/sociais. Por isso o MUGOVERSO não "coleta" anúncio de concorrente brasileiro:
gera o link da Biblioteca já filtrado no concorrente (``ad_library_url``).
"""
from __future__ import annotations

import asyncio
import html as html_lib
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from .ig_supabase import sb_insert, sb_select, sb_update, sb_upsert

PRODUCTS = "benchmark_products"
POINTS = "benchmark_price_points"
MAX_BYTES = 3_000_000
TIMEOUT = 15
UA = "Mozilla/5.0 (compatible; MugoversoBenchmark/1.0; +https://mugoagencia.com.br)"
_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_META_PRICE = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_META_CURRENCY = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:product:price:currency|og:price:currency)["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)


class PriceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    raw = str(value).strip()
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return round(float(re.sub(r"[^\d.]", "", raw)), 2)
    except ValueError:
        return None


# ---------------------------------------------------------------- segurança da busca

def clean_url(value: Any) -> str:
    raw = str(value or "").strip()
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        raise PriceError("INVALID_URL", "Informe o link https da página do produto.")
    return urlunsplit((parts.scheme, parts.hostname.lower(), parts.path or "/", parts.query, ""))


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


async def _fetch(url: str, *, accept: str = "text/html") -> httpx.Response:
    host = urlsplit(url).hostname or ""
    if not await asyncio.to_thread(_public_host, host):
        raise PriceError("BLOCKED_HOST", "Esse endereço não é público.")
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": UA, "Accept": accept}) as client:
        for _ in range(4):  # segue até 3 redirecionamentos, checando cada destino
            resp = await client.get(url)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                url = clean_url(httpx.URL(url).join(resp.headers["location"]))
                if not await asyncio.to_thread(_public_host, urlsplit(url).hostname or ""):
                    raise PriceError("BLOCKED_HOST", "O site redirecionou para um endereço não público.")
                continue
            if len(resp.content) > MAX_BYTES:
                raise PriceError("TOO_BIG", "A página é grande demais para ler.")
            return resp
    raise PriceError("TOO_MANY_REDIRECTS", "O site redirecionou demais.")


# ---------------------------------------------------------------- leitura do preço (puro)

def from_shopify_js(data: Dict[str, Any]) -> Dict[str, Any]:
    variants = [v for v in data.get("variants") or [] if isinstance(v, dict)]
    available = [v for v in variants if v.get("available")]
    pick = min(available or variants, key=lambda v: v.get("price") or 0) if variants else {}
    price = pick.get("price", data.get("price"))
    compare = pick.get("compare_at_price", data.get("compare_at_price"))
    return {"title": str(data.get("title") or "")[:300] or None, "price": round(price / 100, 2) if isinstance(price, (int, float)) else _num(price),
            "compare_at": round(compare / 100, 2) if isinstance(compare, (int, float)) and compare else None,
            "available": bool(available) if variants else data.get("available"), "currency": None,
            "image": (("https:" + data["featured_image"]) if str(data.get("featured_image") or "").startswith("//") else data.get("featured_image")) or None,
            "source": "shopify"}


def _ld_products(node: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_ld_products(item))
    elif isinstance(node, dict):
        kind = node.get("@type")
        if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
            out.append(node)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                out.extend(_ld_products(node[key]))
    return out


def from_html(page: str) -> Dict[str, Any]:
    for block in _LD.findall(page):
        try:
            data = json.loads(html_lib.unescape(block.strip()))
        except ValueError:
            continue
        for product in _ld_products(data):
            offers = product.get("offers")
            offers = offers if isinstance(offers, list) else [offers] if offers else []
            prices, currency, available = [], None, None
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                for key in ("price", "lowPrice"):
                    value = _num(offer.get(key))
                    if value:
                        prices.append(value)
                spec = offer.get("priceSpecification")
                if isinstance(spec, dict) and _num(spec.get("price")):
                    prices.append(_num(spec.get("price")))
                currency = currency or offer.get("priceCurrency")
                status = str(offer.get("availability") or "")
                if status:
                    available = bool(available) or "InStock" in status
            if prices:
                image = product.get("image")
                image = image[0] if isinstance(image, list) and image else image
                image = image.get("url") if isinstance(image, dict) else image
                return {"title": str(product.get("name") or "")[:300] or None, "price": min(prices), "compare_at": None,
                        "available": available, "currency": currency, "image": image if isinstance(image, str) else None, "source": "json_ld"}
    price = _META_PRICE.search(page)
    if price and _num(price.group(1)):
        title = _TITLE.search(page)
        image = _OG_IMAGE.search(page)
        currency = _META_CURRENCY.search(page)
        return {"title": html_lib.unescape(title.group(1).strip())[:300] if title else None, "price": _num(price.group(1)),
                "compare_at": None, "available": None, "currency": currency.group(1) if currency else None,
                "image": image.group(1) if image else None, "source": "meta_tag"}
    raise PriceError("NO_PRICE", "A página não mostra o preço de um jeito que dê para ler (sem dados de produto).")


async def read_price(url: str) -> Dict[str, Any]:
    url = clean_url(url)
    path = urlsplit(url).path
    if "/products/" in path:
        js_url = urlunsplit(("https", urlsplit(url).hostname, path.rstrip("/").split("?")[0] + ".js", "", ""))
        try:
            resp = await _fetch(js_url, accept="application/json")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("variants") is not None:
                    return from_shopify_js(data)
        except (ValueError, httpx.HTTPError, PriceError):
            pass  # não é Shopify (ou bloqueou o .js): segue para a página
    try:
        resp = await _fetch(url)
    except httpx.HTTPError:
        raise PriceError("UNREACHABLE", "O site não respondeu.") from None
    if resp.status_code >= 400:
        raise PriceError(f"HTTP_{resp.status_code}", f"O site respondeu {resp.status_code}.")
    return from_html(resp.text)


async def catalog(website: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Lista produtos de uma loja Shopify (``/products.json``) para escolher quais acompanhar."""
    base = clean_url(website)
    host = urlsplit(base).hostname
    try:
        resp = await _fetch(f"https://{host}/products.json?limit={max(1, min(limit, 50))}", accept="application/json")
        data = resp.json() if resp.status_code == 200 else {}
    except (ValueError, httpx.HTTPError):
        data = {}
    items = []
    for p in (data.get("products") or [])[:limit] if isinstance(data, dict) else []:
        variants = p.get("variants") or []
        price = min((_num(v.get("price")) or 0 for v in variants), default=None)
        image = ((p.get("images") or [{}])[0] or {}).get("src")
        items.append({"title": p.get("title"), "url": f"https://{host}/products/{p.get('handle')}", "price": price, "image": image})
    if not items:
        raise PriceError("NO_CATALOG", "Não deu para listar os produtos desse site (não é Shopify ou bloqueou). Cole o link de cada produto.")
    return items


def ad_library_url(competitor: Dict[str, Any], country: str = "BR") -> str:
    page = str(competitor.get("facebook_page") or "").strip()
    page = re.sub(r"^https?://(www\.)?facebook\.com/", "", page).strip("/")
    if page.isdigit():
        return f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={country}&view_all_page_id={page}"
    term = page or str(competitor.get("name") or "")
    return (f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={country}"
            f"&q={quote(term)}&search_type=keyword_unordered")


# ---------------------------------------------------------------- persistência

FIELDS = "id,competitor_id,url,title,image,price,compare_at,currency,available,source,checked_at,error,active,created_at"


async def add_product(client_id: str, url: str, competitor_id: Optional[str]) -> Dict[str, Any]:
    url = clean_url(url)
    if competitor_id:
        found = await sb_select("benchmark_competitors", select="id", filters={"client_id": f"eq.{client_id}", "id": f"eq.{competitor_id}"}, limit=1)
        if not found:
            raise PriceError("NOT_FOUND", "Concorrente não encontrado nesta empresa.", 404)
    existing = await sb_select(PRODUCTS, select="id", filters={"client_id": f"eq.{client_id}", "url": f"eq.{url}"}, limit=1)
    if existing:
        await sb_update(PRODUCTS, filters={"id": f"eq.{existing[0]['id']}"}, patch={"active": True, "competitor_id": competitor_id}, returning="minimal")
        product_id = existing[0]["id"]
    else:
        count = await sb_select(PRODUCTS, select="id", filters={"client_id": f"eq.{client_id}", "active": "is.true"}, limit=201)
        if len(count) >= 200:
            raise PriceError("LIMIT", "Limite de 200 produtos monitorados por empresa.")
        product_id = (await sb_insert(PRODUCTS, {"client_id": client_id, "competitor_id": competitor_id, "url": url}))["id"]
    return await check_product(client_id, product_id)


async def check_product(client_id: str, product_id: str) -> Dict[str, Any]:
    rows = await sb_select(PRODUCTS, select=FIELDS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{product_id}"}, limit=1)
    if not rows:
        raise PriceError("NOT_FOUND", "Produto não encontrado.", 404)
    product = rows[0]
    stamp = _now()
    try:
        read = await read_price(product["url"])
    except PriceError as exc:
        await sb_update(PRODUCTS, filters={"id": f"eq.{product_id}"}, patch={"checked_at": stamp.isoformat(), "error": exc.message[:300]}, returning="minimal")
        return {**product, "checked_at": stamp.isoformat(), "error": exc.message}
    patch = {k: read.get(k) for k in ("title", "image", "price", "compare_at", "currency", "available", "source") if read.get(k) is not None or k in ("compare_at", "available")}
    patch.update({"checked_at": stamp.isoformat(), "error": None})
    if not patch.get("currency"):
        patch["currency"] = product.get("currency") or "BRL"
    await sb_update(PRODUCTS, filters={"id": f"eq.{product_id}"}, patch=patch, returning="minimal")
    await sb_upsert(POINTS, [{"product_id": product_id, "observed_on": stamp.date().isoformat(), "price": read.get("price"),
                              "compare_at": read.get("compare_at"), "available": read.get("available")}], on_conflict="product_id,observed_on")
    return {**product, **patch}


async def list_products(client_id: str, days: int = 90) -> List[Dict[str, Any]]:
    products = await sb_select(PRODUCTS, select=FIELDS, filters={"client_id": f"eq.{client_id}", "active": "is.true"}, order="created_at.asc", limit=200)
    if not products:
        return []
    since = (_now().date().toordinal() - days)
    since_iso = datetime.fromordinal(since).date().isoformat()
    ids = ",".join(p["id"] for p in products)
    points = await sb_select(POINTS, select="product_id,observed_on,price,compare_at,available",
                             filters={"product_id": f"in.({ids})", "observed_on": f"gte.{since_iso}"}, order="observed_on.asc", limit=20000)
    by_product: Dict[str, List[Dict[str, Any]]] = {}
    for pt in points:
        by_product.setdefault(pt["product_id"], []).append(pt)
    for p in products:
        history = by_product.get(p["id"], [])
        p["history"] = [{"date": h["observed_on"], "price": h["price"]} for h in history]
        p["change"] = price_change(history)
    return products


def price_change(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Última mudança de preço no histórico (de quanto para quanto e quando)."""
    prices = [(h["observed_on"], float(h["price"])) for h in history if h.get("price") is not None]
    for i in range(len(prices) - 1, 0, -1):
        if prices[i][1] != prices[i - 1][1]:
            before, after = prices[i - 1][1], prices[i][1]
            return {"on": prices[i][0], "from": before, "to": after, "pct": round((after / before - 1) * 100, 1) if before else None}
    return None


async def remove_product(client_id: str, product_id: str) -> None:
    rows = await sb_update(PRODUCTS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{product_id}"}, patch={"active": False})
    if not rows:
        raise PriceError("NOT_FOUND", "Produto não encontrado.", 404)


async def run_all() -> Dict[str, Any]:
    """Cron diário: lê o preço de todos os produtos ativos e atualiza o Instagram público dos concorrentes."""
    from . import benchmark
    products = await sb_select(PRODUCTS, select="id,client_id", filters={"active": "is.true"}, order="checked_at.asc.nullsfirst", limit=2000)
    total = {"products": 0, "errors": 0, "instagram": 0}
    for p in products:
        try:
            result = await check_product(p["client_id"], p["id"])
            total["products"] += 1
            total["errors"] += 1 if result.get("error") else 0
        except Exception as exc:  # noqa: BLE001
            total["errors"] += 1
            print(f"[benchmark_prices] product_failed id={p['id']} {type(exc).__name__}")
        await asyncio.sleep(0.5)  # gentileza com os sites
    competitors = await sb_select("benchmark_competitors", select="id,client_id,name,instagram_handle,active",
                                  filters={"active": "is.true", "instagram_handle": "not.is.null"}, limit=2000)
    by_client: Dict[str, List[Dict[str, Any]]] = {}
    for c in competitors:
        by_client.setdefault(c["client_id"], []).append(c)
    for cid, comps in by_client.items():
        try:
            await benchmark.refresh_instagram(cid, comps)
            total["instagram"] += 1
        except Exception as exc:  # noqa: BLE001 — cooldown ou conta sem Meta conectada: segue
            print(f"[benchmark_prices] instagram_skip client_id={cid} {type(exc).__name__}")
    return total
