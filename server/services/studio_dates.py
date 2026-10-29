"""Datas sazonais e comerciais do Brasil para o calendário editorial.

Calculadas, nunca digitadas ano a ano: Páscoa pelo algoritmo gregoriano,
Carnaval a partir dela, Dia das Mães/Pais pelo 2º domingo, Black Friday como
a sexta depois da 4ª quinta de novembro. A empresa pode somar datas próprias
no perfil de marca (aniversário da marca, lançamento, data do nicho).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List

COMMERCIAL = "comercial"
HOLIDAY = "feriado"
AWARENESS = "conscientizacao"
CUSTOM = "marca"


def easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-ésimo dia da semana (0=segunda) do mês."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def black_friday(year: int) -> date:
    return nth_weekday(year, 11, 3, 4) + timedelta(days=1)


def national_dates(year: int) -> List[Dict[str, Any]]:
    pascoa = easter(year)
    bf = black_friday(year)
    rows = [
        (date(year, 1, 1), "Ano Novo", HOLIDAY),
        (pascoa - timedelta(days=47), "Carnaval", HOLIDAY),
        (date(year, 3, 8), "Dia Internacional da Mulher", AWARENESS),
        (date(year, 3, 15), "Dia do Consumidor", COMMERCIAL),
        (pascoa, "Páscoa", COMMERCIAL),
        (date(year, 4, 21), "Tiradentes", HOLIDAY),
        (date(year, 5, 1), "Dia do Trabalho", HOLIDAY),
        (nth_weekday(year, 5, 6, 2), "Dia das Mães", COMMERCIAL),
        (date(year, 6, 12), "Dia dos Namorados", COMMERCIAL),
        (date(year, 6, 24), "São João", AWARENESS),
        (nth_weekday(year, 8, 6, 2), "Dia dos Pais", COMMERCIAL),
        (date(year, 9, 7), "Independência do Brasil", HOLIDAY),
        (date(year, 9, 15), "Dia do Cliente", COMMERCIAL),
        (date(year, 10, 12), "Dia das Crianças", COMMERCIAL),
        (date(year, 11, 20), "Dia da Consciência Negra", HOLIDAY),
        (bf, "Black Friday", COMMERCIAL),
        (bf + timedelta(days=3), "Cyber Monday", COMMERCIAL),
        (date(year, 12, 25), "Natal", COMMERCIAL),
        (date(year, 12, 31), "Réveillon", HOLIDAY),
    ]
    return [{"date": d.isoformat(), "label": label, "kind": kind} for d, label, kind in rows]


_MD = re.compile(r"^(\d{2})-(\d{2})$")


def custom_dates(entries: Iterable[Dict[str, Any]] | None, year: int) -> List[Dict[str, Any]]:
    """Datas do perfil da marca: "MM-DD" (todo ano) ou "AAAA-MM-DD" (uma vez)."""
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("date") or "").strip()
        label = str(entry.get("label") or "").strip()[:80]
        if not label:
            continue
        try:
            match = _MD.match(raw)
            when = date(year, int(match.group(1)), int(match.group(2))) if match else date.fromisoformat(raw)
        except (ValueError, AttributeError):
            continue
        out.append({"date": when.isoformat(), "label": label, "kind": CUSTOM})
    return out


def dates_for_month(month_start: date, custom: Iterable[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """Datas que caem no mês, em ordem, sem duplicar o mesmo rótulo no mesmo dia."""
    year = month_start.year
    candidates = national_dates(year) + custom_dates(custom, year)
    seen = set()
    out = []
    for row in sorted(candidates, key=lambda r: (r["date"], r["label"])):
        d = date.fromisoformat(row["date"])
        key = (row["date"], row["label"].lower())
        if d.year == year and d.month == month_start.month and key not in seen:
            seen.add(key)
            out.append(row)
    return out
