"""Monta o HTML do e-mail a partir de blocos (o editor da tela) — tabelas e estilo inline, como os clientes de
e-mail exigem. Tudo o que vem do usuário é escapado; links só http(s) ou as variáveis de link.

Blocos: logo · titulo · texto · imagem · botao · produtos · divisor · espaco. O rodapé (texto da marca +
descadastro) entra sempre, no fim.
Variáveis no texto: {{nome}}, {{primeiro_nome}}, {{marca}}, {{link_carrinho}}, {{valor_carrinho}}, {{link_loja}}.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Tuple

BLOCK_TYPES = ("logo", "titulo", "texto", "imagem", "botao", "produtos", "divisor", "espaco")
MAX_BLOCKS = 40
VARIABLES = ("nome", "primeiro_nome", "marca", "link_carrinho", "valor_carrinho", "link_loja")
LINK_VARIABLES = ("link_carrinho", "link_loja", "descadastro")
DEFAULT_COLOR = "#004f6e"
_VAR = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SCRIPT = re.compile(r"<\s*(script|iframe|object|embed)\b.*?(</\s*\1\s*>|$)", re.I | re.S)
_ON_ATTR = re.compile(r"\s on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I | re.X)

FONT = "font-family:Helvetica,Arial,sans-serif"


def _text(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def fill(text: str, variables: Dict[str, str]) -> str:
    """Troca as variáveis conhecidas; desconhecidas ficam vazias (nunca aparece {{x}} para o cliente)."""
    return _VAR.sub(lambda m: str(variables.get(m.group(1), "")), text)


def _escaped(text: Any, variables: Dict[str, str], limit: int = 2000) -> str:
    safe = {k: html.escape(str(v)) for k, v in variables.items()}
    return fill(html.escape(_text(text, limit)), safe).replace("\n", "<br>")


def _url(value: Any, variables: Dict[str, str]) -> Optional[str]:
    raw = _text(value, 1000)
    match = _VAR.fullmatch(raw)
    if match and match.group(1) in LINK_VARIABLES:
        raw = str(variables.get(match.group(1)) or "")
    if not re.match(r"^https?://", raw, re.I):
        return None
    return html.escape(raw, quote=True)


def normalize_design(design: Any) -> Dict[str, Any]:
    """Guarda só blocos conhecidos com campos conhecidos (o que vai para o banco e para o HTML)."""
    blocks = []
    for block in ((design or {}).get("blocks") if isinstance(design, dict) else None) or []:
        if not isinstance(block, dict) or block.get("type") not in BLOCK_TYPES:
            continue
        clean = {"type": block["type"]}
        for key, limit in (("text", 4000), ("url", 1000), ("href", 1000), ("alt", 200), ("label", 80), ("align", 10)):
            if key in block and block[key] is not None:
                clean[key] = _text(block[key], limit)
        blocks.append(clean)
        if len(blocks) >= MAX_BLOCKS:
            break
    return {"blocks": blocks}


def _items_html(items: List[Dict[str, Any]], color: str) -> str:
    rows = []
    for item in items[:6]:
        title = html.escape(_text(item.get("title"), 160))
        qty = int(item.get("quantity") or 1)
        price = item.get("price")
        price_txt = f"R$ {float(price):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if price not in (None, "") else ""
        image = _url(item.get("image"), {})
        img = (f'<img src="{image}" width="64" height="64" alt="" style="display:block;border-radius:8px;object-fit:cover">'
               if image else '<div style="width:64px;height:64px;border-radius:8px;background:#f2f0ec"></div>')
        rows.append(
            f'<tr><td style="padding:8px 12px 8px 0;width:64px">{img}</td>'
            f'<td style="padding:8px 0;{FONT};font-size:15px;color:#15181b">{title}'
            f'<div style="font-size:13px;color:#6b7075">{qty} × {price_txt}</div></td></tr>')
    if not rows:
        return ""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-top:1px solid #ece9e3;border-bottom:1px solid #ece9e3;margin:8px 0">{"".join(rows)}</table>')


def _block_html(block: Dict[str, Any], *, variables: Dict[str, str], color: str, logo: Optional[str],
                brand: str, items: List[Dict[str, Any]]) -> str:
    kind = block["type"]
    align = block.get("align") if block.get("align") in ("left", "center") else "left"
    if kind == "logo":
        src = _url(block.get("url") or logo, variables)
        if src:
            return f'<div style="text-align:{align};padding:8px 0 16px"><img src="{src}" alt="{html.escape(brand)}" height="40" style="height:40px;width:auto"></div>'
        return f'<div style="text-align:{align};padding:8px 0 16px;{FONT};font-size:20px;font-weight:700;color:{color}">{html.escape(brand)}</div>'
    if kind == "titulo":
        return f'<h1 style="margin:0 0 12px;{FONT};font-size:26px;line-height:1.25;color:#15181b;text-align:{align}">{_escaped(block.get("text"), variables, 300)}</h1>'
    if kind == "texto":
        return f'<p style="margin:0 0 16px;{FONT};font-size:16px;line-height:1.6;color:#33383d;text-align:{align}">{_escaped(block.get("text"), variables, 4000)}</p>'
    if kind == "imagem":
        src = _url(block.get("url"), variables)
        if not src:
            return ""
        img = f'<img src="{src}" alt="{html.escape(_text(block.get("alt"), 200))}" width="560" style="display:block;width:100%;max-width:560px;height:auto;border-radius:12px">'
        href = _url(block.get("href"), variables)
        linked = f'<a href="{href}">{img}</a>' if href else img
        return f'<div style="margin:0 0 16px">{linked}</div>'
    if kind == "botao":
        href = _url(block.get("href"), variables)
        label = _escaped(block.get("label") or "Ver agora", variables, 80)
        if not href:
            return ""
        return (f'<div style="text-align:{"center" if align == "center" else "left"};margin:8px 0 20px">'
                f'<a href="{href}" style="display:inline-block;padding:14px 28px;border-radius:999px;background:{color};'
                f'color:#ffffff;{FONT};font-size:16px;font-weight:700;text-decoration:none">{label}</a></div>')
    if kind == "produtos":
        return _items_html(items, color)
    if kind == "divisor":
        return '<hr style="border:none;border-top:1px solid #ece9e3;margin:20px 0">'
    if kind == "espaco":
        return '<div style="height:24px;line-height:24px">&nbsp;</div>'
    return ""


def _footer(settings: Dict[str, Any], variables: Dict[str, str], brand: str) -> str:
    footer = _escaped(settings.get("footer_text") or f"Você recebe este e-mail porque é cliente {brand}.", variables, 600)
    unsub = _url(variables.get("descadastro"), {})
    link = f'<br><a href="{unsub}" style="color:#6b7075">Não quero mais receber estes e-mails</a>' if unsub else ""
    return f'<p style="margin:24px 0 0;{FONT};font-size:12px;line-height:1.6;color:#8a8f94;text-align:center">{footer}{link}</p>'


def render(design: Any, settings: Dict[str, Any], variables: Dict[str, str], *, preheader: str = "",
           items: Optional[List[Dict[str, Any]]] = None, custom_html: Optional[str] = None) -> Tuple[str, str]:
    """Devolve (html, texto puro)."""
    brand = _text(settings.get("from_name") or variables.get("marca") or "", 80)
    variables = {**variables, "marca": variables.get("marca") or brand}
    color = settings.get("brand_color") if _COLOR.match(str(settings.get("brand_color") or "")) else DEFAULT_COLOR
    if custom_html:
        return custom_document(custom_html, settings, variables, brand=brand, items=items or [], preheader=preheader)
    parts = [_block_html(b, variables=variables, color=color, logo=settings.get("logo_url"), brand=brand, items=items or [])
             for b in normalize_design(design)["blocks"]]
    inner = "".join(parts) + _footer(settings, variables, brand)
    pre = html.escape(fill(_text(preheader, 200), variables))
    doc = (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title></title></head>'
        '<body style="margin:0;padding:0;background:#f4f2ee">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{pre}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f2ee"><tr>'
        '<td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:16px">'
        f'<tr><td style="padding:32px 36px">{inner}</td></tr></table></td></tr></table></body></html>'
    )
    return doc, to_text(inner)


# ---------------------------------------------------------------- HTML próprio (colado ou importado de arquivo)

MAX_HTML = 300_000
GMAIL_CLIP = 102_000  # o Gmail corta a mensagem acima disso ("Mensagem cortada")
# Atalhos de outras ferramentas viram as nossas variáveis, para importar modelos prontos sem retrabalho.
ALIASES = {
    "*|FNAME|*": "{{primeiro_nome}}", "*|UNSUB|*": "{{descadastro}}", "{{{RESEND_UNSUBSCRIBE_URL}}}": "{{descadastro}}",
    "{{unsubscribe}}": "{{descadastro}}", "{{unsubscribe_url}}": "{{descadastro}}", "{{first_name}}": "{{primeiro_nome}}",
    "{{name}}": "{{nome}}", "{{cart_url}}": "{{link_carrinho}}",
}
_JS_URL = re.compile(r"""(href|src|action)\s*=\s*(["'])\s*(javascript|vbscript):[^"']*\2""", re.I)
_META_REFRESH = re.compile(r"<meta[^>]+http-equiv\s*=\s*[\"']?refresh[^>]*>", re.I)
_FORM = re.compile(r"</?\s*form\b[^>]*>", re.I)
_FULL_DOC = re.compile(r"<\s*(html|body)\b", re.I)
_BODY_OPEN = re.compile(r"<\s*body\b[^>]*>", re.I)
_BODY_CLOSE = re.compile(r"</\s*body\s*>", re.I)
_HEAD = re.compile(r"<\s*head\b.*?</\s*head\s*>", re.I | re.S)
_STYLE = re.compile(r"<\s*style\b.*?</\s*style\s*>", re.I | re.S)


def sanitize_html(raw: str) -> str:
    """Tira o que é perigoso ou que o e-mail não suporta: script, iframe, eventos on*, javascript:, formulário, refresh."""
    out = _SCRIPT.sub("", str(raw or "")[:MAX_HTML])
    out = _ON_ATTR.sub("", out)
    out = _JS_URL.sub(lambda m: f'{m.group(1)}="#"', out)
    out = _META_REFRESH.sub("", out)
    return _FORM.sub("", out)


def normalize_tags(raw: str) -> str:
    out = raw
    for alias, ours in ALIASES.items():
        out = out.replace(alias, ours)
    return out


def html_report(raw: str) -> Dict[str, Any]:
    """O que a tela mostra ao colar/importar: tamanho, corte do Gmail, variáveis usadas e o que foi removido."""
    text = str(raw or "")
    clean = sanitize_html(text)
    used = sorted({m.group(1) for m in _VAR.finditer(normalize_tags(clean))})
    return {"bytes": len(text.encode("utf-8")), "too_big": len(text) > MAX_HTML, "gmail_clip": len(clean.encode("utf-8")) > GMAIL_CLIP,
            "full_document": bool(_FULL_DOC.search(text)), "variables": used, "has_unsubscribe": "descadastro" in used,
            "removed_unsafe": clean != text[:MAX_HTML]}


def custom_document(custom_html: str, settings: Dict[str, Any], variables: Dict[str, str], *, brand: str,
                    items: List[Dict[str, Any]], preheader: str) -> Tuple[str, str]:
    color = settings.get("brand_color") if _COLOR.match(str(settings.get("brand_color") or "")) else DEFAULT_COLOR
    body = normalize_tags(sanitize_html(custom_html))
    has_unsub = bool(re.search(r"\{\{\s*descadastro\s*\}\}", body))
    # {{produtos}} vira a lista de itens do carrinho (HTML pronto, não escapado).
    body = re.sub(r"\{\{\s*produtos\s*\}\}", lambda _m: _items_html(items, color), body)
    body = fill(body, {k: html.escape(str(v), quote=True) for k, v in variables.items()})
    footer = "" if has_unsub or not variables.get("descadastro") else _footer(settings, variables, brand)
    pre = html.escape(fill(_text(preheader, 200), variables))
    pre_div = f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{pre}</div>' if pre else ""
    if _FULL_DOC.search(body):
        # Documento completo (exportado de outra ferramenta): mantém <head>/<style>; entra pré-cabeçalho e rodapé.
        if footer:
            wrapped = f'<div style="max-width:600px;margin:0 auto;padding:0 16px 24px">{footer}</div>'
            body = _BODY_CLOSE.sub(lambda _m: wrapped + "</body>", body, count=1) if _BODY_CLOSE.search(body) else body + wrapped
        if pre_div:
            body = _BODY_OPEN.sub(lambda m: m.group(0) + pre_div, body, count=1) if _BODY_OPEN.search(body) else pre_div + body
        if not body.lstrip().lower().startswith("<!doctype"):
            body = "<!doctype html>" + body
        visible = _BODY_OPEN.split(_HEAD.sub("", body), maxsplit=1)[-1]
        return body, to_text(_STYLE.sub("", visible))
    # Trecho de HTML: entra na moldura padrão (600px, fundo neutro).
    doc = (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title></title></head>'
        f'<body style="margin:0;padding:0;background:#f4f2ee">{pre_div}'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f2ee"><tr>'
        '<td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:16px">'
        f'<tr><td style="padding:32px 36px">{body}{footer}</td></tr></table></td></tr></table></body></html>'
    )
    return doc, to_text(_STYLE.sub("", body + footer))


def to_text(markup: str) -> str:
    text = re.sub(r"<(br|/p|/h1|/tr|/div)\s*/?>", "\n", markup, flags=re.I)
    text = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def default_cart_design() -> Dict[str, Any]:
    return {"blocks": [
        {"type": "logo", "align": "center"},
        {"type": "titulo", "text": "{{primeiro_nome}}, seu carrinho está te esperando"},
        {"type": "texto", "text": "Separamos os itens que você escolheu. É só voltar e finalizar quando quiser."},
        {"type": "produtos"},
        {"type": "botao", "label": "Finalizar minha compra", "href": "{{link_carrinho}}", "align": "center"},
        {"type": "texto", "text": "Ficou com alguma dúvida? É só responder este e-mail."},
    ]}


def default_campaign_design() -> Dict[str, Any]:
    return {"blocks": [
        {"type": "logo", "align": "center"},
        {"type": "titulo", "text": "Novidade para você, {{primeiro_nome}}"},
        {"type": "texto", "text": "Escreva aqui a mensagem da campanha."},
        {"type": "botao", "label": "Ver na loja", "href": "{{link_loja}}", "align": "center"},
    ]}
