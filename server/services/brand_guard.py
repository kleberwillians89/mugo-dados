"""
Trava de fidelidade à marca: revisão automática (sem IA, sem custo) de todo texto gerado antes
de aparecer na tela. Não reescreve nada: aponta, para a equipe decidir.

* palavra proibida: as "palavras a evitar" do Perfil de Marca + clichês proibidos do Studio;
* promessa sem dado: número, porcentagem, preço, frete grátis, brinde ou garantia que não está no
  briefing nem nos dados da conta (a IA não pode inventar oferta);
* urgência inventada: "só hoje", "últimas unidades"... que ninguém pediu.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from .studio_llm import BANNED_CLICHES

CLAIMS = [
    (re.compile(r"\b\d{1,3}\s?%"), "porcentagem"),
    (re.compile(r"R\$\s?\d[\d.,]*"), "preço"),
    (re.compile(r"\bfrete gr[aá]tis\b", re.I), "frete grátis"),
    (re.compile(r"\b(brinde|cupom|cashback)\b", re.I), "brinde/cupom"),
    (re.compile(r"\bgarantia\b", re.I), "garantia"),
]
URGENCY = re.compile(r"\b(s[oó] hoje|[uú]ltimas? (unidades|horas|chance)|acaba hoje|corre que|enquanto durar)\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def check(text: str, *, avoid: Iterable[str] = (), context: str = "") -> List[Dict[str, str]]:
    """Problemas de fidelidade do texto. ``context`` = briefing + dados que o texto pode citar."""
    low, ctx = _norm(text), _norm(context)
    issues: List[Dict[str, str]] = []
    for word in sorted({w.lower().strip() for w in (*BANNED_CLICHES, *avoid) if w and w.strip()}):
        if word in low:
            issues.append({"type": "palavra_proibida", "text": word, "fix": f"Troque “{word}”: está nas palavras a evitar da marca."})
    for pattern, label in CLAIMS:
        for match in {m.group(0).strip() for m in pattern.finditer(text or "")}:
            if _norm(match) not in ctx:
                issues.append({"type": "promessa_sem_dado", "text": match,
                               "fix": f"“{match}” ({label}) não está no briefing nem nos dados. Confirme a oferta ou tire."})
    for match in {m.group(0) for m in URGENCY.finditer(text or "")}:
        if _norm(match) not in ctx:
            issues.append({"type": "urgencia_inventada", "text": match, "fix": f"“{match}” cria urgência que ninguém pediu."})
    return issues


def flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(flatten(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(flatten(v) for v in value)
    return ""


def summary(issues: List[Dict[str, str]]) -> Dict[str, Any]:
    return {"ok": not issues, "issues": issues[:12]}
