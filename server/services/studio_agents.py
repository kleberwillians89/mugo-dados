"""Esteira de agentes de conteúdo (trazida da iAgência, sem a parte de arte).

Um clique roda, de ponta a ponta, o que antes eram cliques separados:

1. Pesquisador      — lê os dados autorizados da marca: perfil, negócio, posts que performaram, vendas por origem,
                      metas, aprendizados de aprovações e tendências (studio_intelligence).
2. Estrategista     — monta a matriz de 4 semanas por plataforma e pilar (studio_matrix.generate).
3. Redator          — escreve gancho, legenda, roteiro (cenas, slides ou telas) e a ideia de imagem de cada pauta.
4. Revisor de marca — confere tom, palavras proibidas, dado inventado e citação de outra marca (brand_guard).
5. Agendador        — põe no Calendário nos melhores dias e horários da conta (sem duplicar).
6. Diretor de arte  — monta o briefing técnico de cada peça, como o Atendimento da iAgência (objetivo,
                      mensagem-chave, entregáveis, requisitos e direção de arte). A peça em si é da equipe/Canva.
7. Aprovação interna— o que passou na revisão vai para "Revisão interna"; o que teve alerta fica em rascunho
                      para a equipe olhar. Nada vai ao cliente sem a equipe.

Pedido de ajuste do cliente: ``suggest_adjustment`` prepara uma nova versão do post (gancho, legenda, roteiro e
briefing visual) a partir do comentário e das referências e guarda como SUGESTÃO no post. A equipe aplica com um
clique ou descarta; nada muda sozinho.

A execução roda em segundo plano (a tela acompanha pelo ``studio_agent_runs``). Uma esteira por marca de cada vez;
se o servidor reiniciar no meio, a execução parada há mais de 20 minutos aparece como interrompida.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select, sb_update
from .studio_calendar import ITEMS_TABLE, StudioError, language_rule, load_profile

RUNS = "studio_agent_runs"
PARALLEL = 2                 # pautas escritas ao mesmo tempo (custo e limite da IA sob controle)
STALE_MINUTES = 20
STEPS: List[Dict[str, str]] = [
    {"key": "pesquisa", "agent": "Pesquisador", "task": "Lê os dados da marca, os posts que performaram, as vendas e as tendências"},
    {"key": "estrategia", "agent": "Estrategista", "task": "Monta a matriz de 4 semanas por plataforma e pilar"},
    {"key": "redacao", "agent": "Redator", "task": "Escreve gancho, legenda e roteiro de cada pauta"},
    {"key": "revisao", "agent": "Revisor de marca", "task": "Confere tom, palavras proibidas e dados inventados"},
    {"key": "agenda", "agent": "Agendador", "task": "Coloca no Calendário nos melhores dias e horários"},
    {"key": "direcao_arte", "agent": "Diretor de arte", "task": "Monta o briefing técnico e a direção de arte de cada peça"},
    {"key": "aprovacao", "agent": "Aprovação interna", "task": "Envia para a equipe revisar antes do cliente"},
]
_TASKS: set = set()          # referência das tarefas em segundo plano (o asyncio só guarda referência fraca)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh_steps() -> List[Dict[str, Any]]:
    return [{**s, "status": "pendente", "detail": None} for s in STEPS]


def _background(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


# ---------------------------------------------------------------- execuções

def _expire(run: Dict[str, Any]) -> Dict[str, Any]:
    """Execução 'rodando' sem andar há mais de 20 min: o servidor reiniciou no meio."""
    if run.get("status") != "rodando":
        return run
    try:
        updated = datetime.fromisoformat(str(run.get("updated_at")).replace("Z", "+00:00"))
    except ValueError:
        return run
    if _now() - updated < timedelta(minutes=STALE_MINUTES):
        return run
    steps = [{**s, "status": "falhou" if s.get("status") == "rodando" else s.get("status")} for s in run.get("steps") or []]
    return {**run, "status": "falhou", "steps": steps, "error": "A esteira foi interrompida (o servidor reiniciou). Rode de novo."}


async def latest_run(client_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(RUNS, select="*", filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=1)
    if not rows:
        return None
    run = rows[0]
    expired = _expire(run)
    if expired is not run:
        await sb_update(RUNS, filters={"id": f"eq.{run['id']}", "status": "eq.rodando"},
                        patch={"status": "falhou", "steps": expired["steps"], "error": expired["error"],
                               "finished_at": _now().isoformat(), "updated_at": _now().isoformat()})
    return expired


async def start_run(client_id: str, *, user_id: str) -> Dict[str, Any]:
    """Abre a execução e roda a esteira em segundo plano. Uma por marca de cada vez."""
    current = await latest_run(client_id)
    if current and current.get("status") == "rodando":
        raise StudioError("AGENTS_RUNNING", "A esteira desta marca já está rodando.")
    profile = (await load_profile(client_id))["profile"]
    if not any((p or {}).get("name") for p in profile.get("pillars") or []):
        raise StudioError("MATRIX_PILLARS_REQUIRED")
    if not profile.get("editorial_platforms"):
        raise StudioError("MATRIX_PLATFORMS_REQUIRED")
    run = await sb_insert(RUNS, {"client_id": client_id, "status": "rodando", "steps": _fresh_steps(), "created_by": user_id})
    if not run or not run.get("id"):
        raise StudioError("AGENTS_SAVE_FAILED", "Não foi possível iniciar a esteira.")
    _background(execute(client_id, run, user_id=user_id))
    return run


class _Run:
    """Andamento de uma execução, salvo a cada passo (a tela lê ao vivo)."""

    def __init__(self, client_id: str, run: Dict[str, Any]):
        self.client_id = client_id
        self.id = run["id"]
        self.steps = [dict(s) for s in run.get("steps") or _fresh_steps()]
        self.extra: Dict[str, Any] = {}

    async def save(self, **patch: Any) -> None:
        self.extra.update(patch)
        await sb_update(RUNS, filters={"id": f"eq.{self.id}"},
                        patch={"steps": self.steps, "updated_at": _now().isoformat(), **patch})

    async def step(self, key: str, status: str, detail: Optional[str] = None) -> None:
        for s in self.steps:
            if s["key"] == key:
                s["status"] = status
                if detail is not None:
                    s["detail"] = detail[:300]
        await self.save()


async def execute(client_id: str, run: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    """Os sete agentes em sequência. Qualquer falha encerra a execução com o motivo (o que já foi feito fica)."""
    from . import studio_matrix as matrix
    from .studio_calendar import update_item
    from .studio_engines import generate_briefing
    from .studio_intelligence import build_content_intelligence, coverage

    state = _Run(client_id, run)
    current = "pesquisa"
    try:
        # 1. Pesquisador
        await state.step("pesquisa", "rodando")
        intel = await build_content_intelligence(client_id, use_cache=False)
        cov = coverage(intel)
        found = [f"{cov['posts_analisados']} posts analisados"]
        if cov["campanhas"]:
            found.append(f"{cov['campanhas']} campanhas que venderam")
        if cov["aprovados"] or cov["ajustes"]:
            found.append(f"{cov['aprovados']} aprovações e {cov['ajustes']} ajustes do cliente")
        if cov["lacunas"]:
            found.append(f"faltam dados: {', '.join(cov['lacunas'][:3])}")
        await state.step("pesquisa", "feito", "; ".join(found))

        # 2. Estrategista
        current = "estrategia"
        await state.step("estrategia", "rodando")
        built = await matrix.generate(client_id, {}, user_id=user_id)
        ops = [o for o in built.get("opportunities") or [] if o.get("status") != "descartada"]
        await state.save(matrix_id=built["id"])
        await state.step("estrategia", "feito", f"{len(ops)} pautas em 4 semanas" + (f". {built['notes'][0]}" if built.get("notes") else ""))

        # 3. Redator (texto, roteiro e ideia de imagem de cada pauta)
        current = "redacao"
        await state.step("redacao", "rodando", f"0 de {len(ops)}")
        written: Dict[str, Dict[str, Any]] = {}
        failed = 0
        gate = asyncio.Semaphore(PARALLEL)

        async def write(op: Dict[str, Any]) -> None:
            nonlocal failed
            async with gate:
                try:
                    written[op["id"]] = await matrix.create_content(client_id, op["id"], throttle_calls=False)
                except Exception as exc:  # noqa: BLE001 — uma pauta que falhou não derruba a esteira
                    failed += 1
                    print(f"[studio][agents] client_id={client_id} content_failed={type(exc).__name__}")
                await state.step("redacao", "rodando", f"{len(written)} de {len(ops)}")

        await asyncio.gather(*(write(op) for op in ops))
        if not written:
            raise StudioError("AI_INVALID_OUTPUT", "O redator não conseguiu escrever nenhuma pauta. Rode de novo.")
        await state.step("redacao", "feito", f"{len(written)} de {len(ops)} pautas escritas" + (f" ({failed} falharam, ficam na Matriz)" if failed else ""))

        # 4. Revisor de marca (o alerta de cada pauta já vem do brand_guard)
        current = "revisao"
        await state.step("revisao", "rodando")
        flagged = {oid for oid, o in written.items() if o.get("guard")}
        await state.step("revisao", "feito", "Tudo dentro do tom da marca" if not flagged
                         else f"{len(flagged)} pauta(s) com alerta: ficam em rascunho para a equipe conferir")

        # 5. Agendador
        current = "agenda"
        await state.step("agenda", "rodando")
        exported = await matrix.export_to_calendar(client_id, built["id"], user_id=user_id, ids=list(written))
        by_op = {o["id"]: o.get("calendar_item_id") for o in (exported.get("matrix") or {}).get("opportunities") or []}
        item_ids = [i for i in exported.get("calendar_item_ids") or [] if i]
        await state.save(item_ids=item_ids)
        await state.step("agenda", "feito", f"{exported.get('created', 0)} posts no Calendário nos melhores horários")

        # 6. Diretor de arte: briefing técnico de cada peça (o mesmo do Atendimento da iAgência)
        current = "direcao_arte"
        posts = [by_op[oid] for oid in written if by_op.get(oid)]
        await state.step("direcao_arte", "rodando", f"0 de {len(posts)}")
        briefed = 0

        async def brief(item_id: str) -> None:
            nonlocal briefed
            async with gate:
                try:
                    await generate_briefing(client_id, item_id, throttle_calls=False)
                    briefed += 1
                except Exception as exc:  # noqa: BLE001 — sem briefing, o post segue com a ideia de imagem do redator
                    print(f"[studio][agents] client_id={client_id} briefing_failed={type(exc).__name__}")
                await state.step("direcao_arte", "rodando", f"{briefed} de {len(posts)}")

        await asyncio.gather(*(brief(i) for i in posts))
        await state.step("direcao_arte", "feito", f"{briefed} briefings técnicos com direção de arte para a equipe produzir")

        # 7. Aprovação interna (só o que passou na revisão)
        current = "aprovacao"
        await state.step("aprovacao", "rodando")
        sent = 0
        for oid in written:
            item_id = by_op.get(oid)
            if not item_id or oid in flagged:
                continue
            try:
                await update_item(client_id, item_id, {"status": "em_revisao"}, user_id=user_id)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[studio][agents] client_id={client_id} review_failed={type(exc).__name__}")
        await state.step("aprovacao", "feito", f"{sent} posts em Revisão interna" + (f"; {len(flagged)} em rascunho com alerta" if flagged else ""))

        summary = (f"{sent} posts prontos para a revisão interna"
                   + (f", {len(flagged)} com alerta em rascunho" if flagged else "")
                   + ". A arte fica com a equipe: cada post traz o briefing técnico e a direção de arte.")
        await state.save(status="concluida", summary=summary, finished_at=_now().isoformat())
    except Exception as exc:  # noqa: BLE001
        message = str(exc) if isinstance(exc, StudioError) and str(exc) != exc.code else "Uma etapa falhou. Rode a esteira de novo."
        if isinstance(exc, StudioError) and exc.code == "AI_RATE_LIMIT":
            message = "Muitas chamadas à IA agora. Espere um minuto e rode de novo."
        print(f"[studio][agents] client_id={client_id} step={current} failed={type(exc).__name__}")
        await state.step(current, "falhou")
        await state.save(status="falhou", error=message[:1000], finished_at=_now().isoformat())
    return {"id": state.id, "steps": state.steps, **state.extra}


# ---------------------------------------------------------------- sugestão para o ajuste pedido

SUGGESTION_SCHEMA_FIELDS = ("gancho", "legenda", "roteiro", "ideia_imagem", "o_que_mudou")


async def suggest_adjustment(client_id: str, item_id: str, note: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Nova versão do post a partir do pedido do cliente (comentário + referências). Guarda como sugestão."""
    from .studio_intelligence import build_content_intelligence, to_prompt
    from .studio_llm import STR, llm_json, obj
    from .studio_references import list_references

    rows = await sb_select(ITEMS_TABLE, select="id,format,channel,title,hook,caption_draft,script,visual_idea,review_note,pillar",
                           filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
    if not rows:
        return None
    item = rows[0]
    ask = (note or item.get("review_note") or "").strip()
    if not ask:
        return None
    refs = await list_references(client_id, item_id)
    profile = (await load_profile(client_id))["profile"]
    intel = await build_content_intelligence(client_id)
    current = {k: item.get(k) for k in ("format", "title", "hook", "caption_draft", "script", "visual_idea")}
    ref_text = "\n".join(f"- {r.get('url')}" + (f" ({r['note']})" if r.get("note") else "") for r in refs[:10])
    prompt = (f"POST ATUAL:\n{json.dumps(current, ensure_ascii=False)}\n\n"
              f"PEDIDO DE AJUSTE DO CLIENTE (atenda exatamente o que ele pediu, sem mudar o resto):\n{ask[:1500]}\n"
              + (f"\nREFERÊNCIAS QUE O CLIENTE MANDOU (links/imagens no estilo que ele quer):\n{ref_text}\n" if ref_text else "")
              + "\nDevolva a nova versão completa: gancho, legenda, roteiro e ideia de imagem (briefing visual para a equipe "
                "produzir a arte). Se o pedido for só sobre a arte, mantenha os textos e reescreva a ideia de imagem. "
                "Em 'o_que_mudou', uma frase curta para a equipe. Sem travessão. Não invente oferta, preço ou prazo.\n"
              + f"\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(profile)}")
    data = await llm_json(client_id=client_id, prompt=prompt, schema_name="studio_adjust_suggestion",
                          instructions="Você é social media sênior de agência. Ajusta o post exatamente como o cliente pediu, no tom da marca.",
                          schema=obj({k: STR for k in SUGGESTION_SCHEMA_FIELDS}), temperature=0.5)
    suggestion = {"hook": str(data.get("gancho") or "").strip()[:400] or None,
                  "caption_draft": str(data.get("legenda") or "").strip()[:4000] or None,
                  "script": str(data.get("roteiro") or "").strip()[:4000] or None,
                  "visual_idea": str(data.get("ideia_imagem") or "").strip()[:2000] or None,
                  "summary": str(data.get("o_que_mudou") or "").strip()[:300] or None,
                  "note": ask[:1000], "created_at": _now().isoformat()}
    if not (suggestion["hook"] or suggestion["caption_draft"] or suggestion["visual_idea"]):
        return None
    await sb_update(ITEMS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, patch={"ai_suggestion": suggestion})
    return suggestion


def schedule_adjustment(client_id: str, item_id: Optional[str], note: Optional[str]) -> None:
    """Chamado quando o cliente pede ajuste: prepara a sugestão em segundo plano (nunca atrasa a resposta)."""
    if not item_id:
        return

    async def run() -> None:
        try:
            await suggest_adjustment(client_id, item_id, note)
        except Exception as exc:  # noqa: BLE001 — sem sugestão, a equipe ajusta como sempre
            print(f"[studio][agents] client_id={client_id} suggestion_failed={type(exc).__name__}")
    try:
        _background(run())
    except RuntimeError:  # sem loop rodando (script/teste síncrono)
        pass


async def apply_suggestion(client_id: str, item_id: str, *, user_id: str) -> Dict[str, Any]:
    """Equipe aceitou: a sugestão vira o conteúdo do post (com histórico) e sai da fila."""
    from .studio_calendar import update_item
    rows = await sb_select(ITEMS_TABLE, select="id,ai_suggestion", filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
    suggestion = (rows[0].get("ai_suggestion") if rows else None) or None
    if not suggestion:
        raise StudioError("SUGGESTION_NOT_FOUND", "Não há sugestão da IA neste post.")
    patch = {k: suggestion[k] for k in ("hook", "caption_draft") if suggestion.get(k)}
    if patch:
        await update_item(client_id, item_id, patch, user_id=user_id)
    extra = {k: suggestion[k] for k in ("script", "visual_idea") if suggestion.get(k)}
    out = await sb_update(ITEMS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"},
                          patch={**extra, "ai_suggestion": None})
    return out[0] if out else {}


async def dismiss_suggestion(client_id: str, item_id: str) -> None:
    await sb_update(ITEMS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, patch={"ai_suggestion": None})
