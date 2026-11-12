"""Esteira de agentes de conteúdo (trazida da iAgência, sem a parte de arte).

Um clique roda, de ponta a ponta, o que antes eram cliques separados:

1. Pesquisador      — lê TUDO da marca (studio_intelligence): perfil, negócio e documentos, posts que performaram,
                      vendas por origem e produtos, metas, aprovações e ajustes, Clipping e concorrentes, voz do
                      público, briefings aprovados, planejamentos, eventos próximos e o acervo da Biblioteca.
2. Estrategista     — monta a Matriz do período pedido (1 a 8 semanas; 4 por padrão) por plataforma e pilar.
   >> PAUSA: a esteira para na Matriz ("aguardando") para a equipe conferir, editar, selecionar ou descartar.
      O botão "Gerar conteúdo" (``continue_run``) segue com as pautas que ficaram (fase 2).
3. Redator          — escreve gancho, legenda, roteiro (cenas, slides ou telas) e a ideia de imagem de cada pauta.
4. Editor-chefe    — lê cada peça com o contexto inteiro e as outras peças do lote: dá nota de 0 a 10 (gancho, aderência
                      ao foco/plano, verdade dos dados, tom, CTA e variedade) e REESCREVE o que ficou abaixo de 8. Depois
                      o brand_guard confere palavras proibidas, dado inventado e citação de outra marca. Peça que nasceu
                      muito fraca (abaixo de 5) fica em rascunho com o motivo, mesmo reescrita.
5. Agendador        — põe no Calendário nos melhores dias e horários da conta (sem duplicar).
6. Diretor de arte  — monta o briefing técnico de cada peça, como o Atendimento da iAgência (objetivo,
                      mensagem-chave, entregáveis, requisitos e direção de arte). A peça em si é da equipe/Canva.
7. Aprovação interna— o que passou na revisão vai para "Revisão interna"; o que teve alerta fica em rascunho
                      para a equipe olhar. Nada vai ao cliente sem a equipe.

Pedido de ajuste do cliente: ``suggest_adjustment`` prepara uma nova versão do post (gancho, legenda, roteiro e
briefing visual) a partir do comentário e das referências e guarda como SUGESTÃO no post. A equipe aplica com um
clique ou descarta; nada muda sozinho.

A execução roda em segundo plano (a tela acompanha pelo ``studio_agent_runs``). Uma esteira por marca de cada vez:
pedido que chega com ela ocupada (Briefing → Social Media, por exemplo) entra na fila ("na_fila") e roda na ordem;
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
    {"key": "pesquisa", "agent": "Pesquisador", "task": "Lê tudo da marca: dados, documentos, briefings, planejamentos, eventos e Biblioteca"},
    {"key": "estrategia", "agent": "Estrategista", "task": "Monta a Matriz do período por plataforma e pilar e para para a equipe conferir"},
    {"key": "redacao", "agent": "Redator", "task": "Escreve gancho, legenda e roteiro de cada pauta"},
    {"key": "revisao", "agent": "Editor-chefe", "task": "Dá nota a cada peça, reescreve o que ficou abaixo de 8 e confere a marca"},
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


ACTIVE = ("rodando", "aguardando")


async def latest_run(client_id: str) -> Optional[Dict[str, Any]]:
    """A execução que a tela mostra: a ativa (rodando ou parada na Matriz) ou, sem ativa, a mais recente.
    Traz ``queued`` = quantos pedidos esperam na fila."""
    rows = await sb_select(RUNS, select="*", filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=20)
    if not rows:
        return None
    out = []
    for row in rows:
        expired = _expire(row)
        if expired is not row:  # parou no meio (servidor reiniciou): grava como falha
            await sb_update(RUNS, filters={"id": f"eq.{row['id']}", "status": "eq.rodando"},
                            patch={"status": "falhou", "steps": expired["steps"], "error": expired["error"],
                                   "finished_at": _now().isoformat(), "updated_at": _now().isoformat()})
        out.append(expired)
    run = (next((r for r in out if r.get("status") in ACTIVE), None)
           or next((r for r in out if r.get("status") != "na_fila"), out[0]))
    return {**run, "queued": sum(1 for r in out if r.get("status") == "na_fila")}


def run_options(*, focus: Optional[str] = None, weeks: Optional[int] = None, start: Optional[str] = None,
                brief_id: Optional[str] = None, auto: bool = False) -> Dict[str, Any]:
    """O que a execução usa: foco/briefing, período e de onde veio. ``auto`` pula a pausa na Matriz."""
    out: Dict[str, Any] = {}
    if focus and str(focus).strip():
        out["focus"] = str(focus).strip()[:1000]
    if weeks:
        out["weeks"] = int(weeks)
    if start:
        out["start"] = str(start)[:10]
    if brief_id:
        out["brief_id"] = str(brief_id)
    if auto:
        out["auto"] = True
    return out


async def start_run(client_id: str, *, user_id: str, focus: Optional[str] = None, weeks: Optional[int] = None,
                    start: Optional[str] = None, brief_id: Optional[str] = None, auto: bool = False) -> Dict[str, Any]:
    """Abre a execução. Com a esteira livre, roda a fase 1 (pesquisa + Matriz) em segundo plano;
    ocupada (rodando ou parada na Matriz), o pedido entra na fila e roda quando a anterior terminar."""
    profile = (await load_profile(client_id))["profile"]
    if not any((p or {}).get("name") for p in profile.get("pillars") or []):
        raise StudioError("MATRIX_PILLARS_REQUIRED")
    if not profile.get("editorial_platforms"):
        raise StudioError("MATRIX_PLATFORMS_REQUIRED")
    options = run_options(focus=focus, weeks=weeks, start=start, brief_id=brief_id, auto=auto)
    if weeks is not None or start:
        from .studio_matrix import request_period
        request_period(options, datetime.now(timezone.utc).date())  # período inválido falha já, não na fila
    current = await latest_run(client_id)
    busy = bool(current and current.get("status") in ACTIVE)
    run = await sb_insert(RUNS, {"client_id": client_id, "status": "na_fila" if busy else "rodando", "steps": _fresh_steps(),
                                 **({"options": options} if options else {}), "created_by": user_id})
    if not run or not run.get("id"):
        raise StudioError("AGENTS_SAVE_FAILED", "Não foi possível iniciar a esteira.")
    if not busy:
        _background(execute(client_id, run, user_id=user_id))
    return run


async def continue_run(client_id: str, run_id: str, *, user_id: str) -> Dict[str, Any]:
    """'Gerar conteúdo': a equipe conferiu a Matriz e a esteira segue para a fase 2 (redação até a aprovação)."""
    rows = await sb_update(RUNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{run_id}", "status": "eq.aguardando"},
                           patch={"status": "rodando", "updated_at": _now().isoformat()})
    if not rows:
        raise StudioError("AGENTS_NOT_WAITING", "Esta esteira não está esperando a Matriz.")
    _background(execute(client_id, rows[0], user_id=user_id, phase=2))
    return rows[0]


async def cancel_run(client_id: str, run_id: str) -> Dict[str, Any]:
    """Descarta a execução parada na Matriz (ou um pedido na fila). A Matriz fica salva para uso manual."""
    rows = await sb_update(RUNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{run_id}", "status": "in.(aguardando,na_fila)"},
                           patch={"status": "cancelada", "finished_at": _now().isoformat(), "updated_at": _now().isoformat()})
    if not rows:
        raise StudioError("AGENTS_NOT_WAITING", "Só dá para cancelar a esteira parada na Matriz ou na fila.")
    await start_next(client_id)
    return rows[0]


async def start_next(client_id: str) -> Optional[Dict[str, Any]]:
    """Terminou (ou foi cancelada): o próximo da fila começa. Só um por vez por marca."""
    rows = await sb_select(RUNS, select="*", filters={"client_id": f"eq.{client_id}", "status": "in.(rodando,aguardando,na_fila)"},
                           order="created_at.asc", limit=20)
    if any(r.get("status") in ACTIVE for r in rows):
        return None
    queued = [r for r in rows if r.get("status") == "na_fila"]
    if not queued:
        return None
    nxt = await sb_update(RUNS, filters={"id": f"eq.{queued[0]['id']}", "status": "eq.na_fila"},
                          patch={"status": "rodando", "updated_at": _now().isoformat()})
    if not nxt:
        return None
    _background(execute(client_id, nxt[0], user_id=str(nxt[0].get("created_by") or "")))
    return nxt[0]


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


def research_summary(cov: Dict[str, Any], intel: Dict[str, Any]) -> str:
    """O que o Pesquisador encontrou, em uma linha para a tela."""
    found = [f"{cov['posts_analisados']} posts analisados"]
    if cov["campanhas"]:
        found.append(f"{cov['campanhas']} campanhas que venderam")
    if cov["aprovados"] or cov["ajustes"]:
        found.append(f"{cov['aprovados']} aprovações e {cov['ajustes']} ajustes do cliente")
    if intel.get("voz_do_publico"):
        found.append("voz do público (comentários, Direct e notícias)")
    if intel.get("produtos_mais_vendidos"):
        found.append(f"{len(intel['produtos_mais_vendidos'])} produtos que mais vendem")
    health = intel.get("saude_da_marca") or {}
    if health.get("indice") is not None:
        found.append(f"saúde da marca {health['indice']}/100")
    if (intel.get("concorrentes") or {}).get("cadastrados"):
        found.append(f"{len(intel['concorrentes']['cadastrados'])} concorrentes")
    if (intel.get("negocio") or {}).get("conhecimento_da_marca"):
        found.append("documentos da marca")
    plans = intel.get("planos_aprovados") or {}
    if intel.get("briefings_aprovados"):
        found.append(f"{len(intel['briefings_aprovados'])} briefing(s) aprovado(s)")
    if plans.get("planejamentos"):
        found.append(f"planejamento \"{plans['planejamentos'][0].get('titulo', '')}\"")
    if plans.get("eventos"):
        found.append(f"{len(plans['eventos'])} evento(s) próximo(s)")
    library = sum(len(v) for v in (intel.get("biblioteca") or {}).values())
    if library:
        found.append(f"{library} arquivo(s) da Biblioteca")
    if cov["lacunas"]:
        found.append(f"faltam dados: {', '.join(cov['lacunas'][:3])}")
    return "; ".join(found)


def matrix_targets(opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pautas que a fase 2 escreve: se a equipe selecionou alguma, só as selecionadas; senão todas não descartadas.
    O que já foi para o Calendário não é escrito de novo."""
    alive = [o for o in opportunities if o.get("status") not in ("descartada", "exportada") and not o.get("calendar_item_id")]
    chosen = [o for o in alive if o.get("status") == "selecionada"]
    return chosen or alive


async def execute(client_id: str, run: Dict[str, Any], *, user_id: str, phase: int = 1) -> Dict[str, Any]:
    """Fase 1: Pesquisador e Estrategista, e para na Matriz ('aguardando') para a equipe conferir.
    Fase 2 ('Gerar conteúdo'): Redator, Revisor, Agendador, Diretor de arte e Aprovação interna, só com as pautas
    que ficaram na Matriz. Com ``auto`` nas opções, roda tudo direto. Falha encerra com o motivo (o feito fica)."""
    from . import studio_matrix as matrix
    from .studio_calendar import update_item
    from .studio_engines import generate_briefing
    from .studio_intelligence import build_content_intelligence, coverage

    state = _Run(client_id, run)
    options = run.get("options") or {}
    current = "pesquisa" if phase == 1 else "redacao"
    try:
        if phase == 1:
            # 1. Pesquisador
            await state.step("pesquisa", "rodando")
            intel = await build_content_intelligence(client_id, use_cache=False)
            await state.step("pesquisa", "feito", research_summary(coverage(intel), intel))

            # 2. Estrategista
            current = "estrategia"
            await state.step("estrategia", "rodando")
            request = {k: options[k] for k in ("focus", "weeks", "start") if options.get(k)}
            built = await matrix.generate(client_id, request, user_id=user_id)
            ops = [o for o in built.get("opportunities") or [] if o.get("status") != "descartada"]
            await state.save(matrix_id=built["id"])
            weeks = int(built.get("weeks") or options.get("weeks") or matrix.WEEKS)
            await state.step("estrategia", "feito", f"{len(ops)} pautas em {weeks} semana{'s' if weeks > 1 else ''}"
                             + (f". {built['notes'][0]}" if built.get("notes") else ""))
            if not options.get("auto"):
                await state.save(status="aguardando",
                                 summary="Matriz pronta. Confira, edite, selecione ou descarte as pautas e clique em Gerar conteúdo.")
                return {"id": state.id, "steps": state.steps, **state.extra}
            matrix_id = built["id"]
        else:
            matrix_id = run.get("matrix_id")
            if not matrix_id:
                raise StudioError("MATRIX_NOT_FOUND", "A Matriz desta esteira não foi encontrada. Rode de novo.")
            await state.save(summary=None)

        ops = matrix_targets((await matrix.get_matrix(client_id, matrix_id)).get("opportunities") or [])
        if not ops:
            raise StudioError("MATRIX_NOTHING_SELECTED", "Nenhuma pauta ficou na Matriz para escrever.")

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

        # 4. Editor-chefe: nota, reescrita do que ficou fraco e conferência da marca
        current = "revisao"
        await state.step("revisao", "rodando", f"0 de {len(written)}")
        reviews: Dict[str, Dict[str, Any]] = {}
        lote = [{"id": oid, "titulo": o.get("title"), "gancho": o.get("hook"), "formato": o.get("format")} for oid, o in written.items()]

        async def review(oid: str) -> None:
            async with gate:
                try:
                    reviews[oid] = await edit_piece(client_id, written[oid], lote, focus=str(options.get("focus") or ""))
                    written[oid] = reviews[oid].pop("op", written[oid])
                except Exception as exc:  # noqa: BLE001 — sem editor, a peça segue com o alerta do brand_guard
                    print(f"[studio][agents] client_id={client_id} editor_failed={type(exc).__name__}")
                await state.step("revisao", "rodando", f"{len(reviews)} de {len(written)}")

        await asyncio.gather(*(review(oid) for oid in list(written)))
        flagged = {oid for oid, o in written.items() if o.get("guard")}
        await state.step("revisao", "feito", review_summary(reviews, flagged))

        # 5. Agendador
        current = "agenda"
        await state.step("agenda", "rodando")
        exported = await matrix.export_to_calendar(client_id, matrix_id, user_id=user_id, ids=list(written))
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
    try:
        await start_next(client_id)
    except Exception as exc:  # noqa: BLE001 — a fila tenta de novo no próximo término
        print(f"[studio][agents] client_id={client_id} queue_failed={type(exc).__name__}")
    return {"id": state.id, "steps": state.steps, **state.extra}


# ---------------------------------------------------------------- Editor-chefe

EDITOR_ROLE = ("Você é editor-chefe de conteúdo de uma agência exigente. Lê a peça com TUDO o que se sabe da marca e com o "
               "lote inteiro do período. É duro e específico: peça genérica, gancho fraco, CTA vaga, dado que não está nos "
               "DADOS ou peça parecida com outra do lote não passa. Quando reescreve, mantém o tema e o formato da pauta.")
EDITOR_FIELDS = (("gancho", "hook", 400), ("legenda", "caption_draft", 4000), ("roteiro", "script", 4000), ("ideia_imagem", "visual_idea", 2000))
PASS_SCORE = 8               # abaixo disso, reescreve
WEAK_SCORE = 5               # abaixo disso, mesmo reescrita, a equipe olha antes (rascunho com o motivo)


def _score(value: Any) -> int:
    try:
        return max(0, min(10, int(float(value))))
    except (TypeError, ValueError):
        return 0


async def edit_piece(client_id: str, op: Dict[str, Any], lote: List[Dict[str, Any]], *, focus: str = "") -> Dict[str, Any]:
    """Nota de 0 a 10 com o contexto inteiro; abaixo de 8, aplica a reescrita; depois roda o brand_guard de novo."""
    from . import studio_matrix as matrix
    from .studio_intelligence import LIBRARY_RULE, PLANS_RULE, build_content_intelligence, passages_for, to_prompt
    from .studio_llm import INT, STR, arr, llm_json, obj

    profile = (await load_profile(client_id))["profile"]
    intel = await build_content_intelligence(client_id)
    passages = await passages_for(client_id, str(op.get("title") or ""), str(op.get("angle") or ""))
    piece = {k: op.get(k) for k in ("platform", "pillar", "format", "title", "hook", "angle", "caption_draft", "script", "visual_idea")}
    others = [x for x in lote if x.get("id") != op.get("id")][:30]
    prompt = (f"PEÇA:\n{json.dumps(piece, ensure_ascii=False)}\n"
              + (f"\nFOCO DO PERÍODO (briefing da equipe):\n{focus[:1500]}\n" if focus else "")
              + f"\nOUTRAS PEÇAS DO LOTE (não pode parecer com nenhuma; abertura e CTA diferentes):\n{json.dumps(others, ensure_ascii=False)}\n"
              + (f"\nTRECHOS DOS DOCUMENTOS DA MARCA:\n{passages}\n" if passages else "")
              + "\nAvalie de 0 a 10, pensando no que faz ESTA marca vender e crescer: gancho (para o dedo nos 2 primeiros segundos?), "
                "aderência ao foco, ao planejamento e aos briefings, verdade (só fatos dos DADOS), tom da marca, CTA clara, "
                "formato bem usado e diferença das outras peças. Em 'problemas', até 4 itens curtos e concretos. "
                f"Se a nota for menor que {PASS_SCORE}, reescreva gancho, legenda, roteiro e ideia de imagem corrigindo os problemas; "
                "se for 8 ou mais, devolva esses campos vazios. "
                f"{LIBRARY_RULE} {PLANS_RULE} Sem travessão. Não invente oferta, preço, número ou prazo.\n"
              + f"\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(profile)}")
    data = await llm_json(client_id=client_id, instructions=EDITOR_ROLE, prompt=prompt, schema_name="studio_editor_chefe",
                          schema=obj({"nota": INT, "problemas": arr(STR), **{k: STR for k, _, _ in EDITOR_FIELDS}}), temperature=0.4)
    score = _score(data.get("nota"))
    problems = [" ".join(str(p).split())[:200] for p in data.get("problemas") or [] if str(p).strip()][:4]
    patch: Dict[str, Any] = {}
    if score < PASS_SCORE:
        for key, column, limit in EDITOR_FIELDS:
            value = str(data.get(key) or "").strip()[:limit]
            if value and value != (op.get(column) or ""):
                patch[column] = value
    merged = {**op, **patch}
    guard = matrix._guard(merged, list(profile.get("keywords_avoid") or []), matrix._guard_context(profile, intel, focus))
    if score < WEAK_SCORE:
        guard = [{"type": "editor", "text": "; ".join(problems) or "Peça fraca",
                  "fix": f"Editor-chefe deu {score}/10 e reescreveu. Confira antes de mandar para o cliente."}, *guard][:6]
    note = f"Editor-chefe: {score}/10" + (" e reescreveu" if patch else "") + (f" ({'; '.join(problems[:2])})" if problems and patch else "") + "."
    rationale = (" ".join(x for x in (str(op.get("rationale") or "").split(" Editor-chefe:")[0].strip(), note) if x))[:1200]
    rows = await sb_update(matrix.OPPORTUNITIES, filters={"client_id": f"eq.{client_id}", "id": f"eq.{op['id']}", "status": "neq.exportada"},
                           patch={**patch, "guard": guard, "rationale": rationale, "updated_at": _now().isoformat()})
    return {"score": score, "problems": problems, "rewritten": bool(patch), "op": rows[0] if rows else {**merged, "guard": guard, "rationale": rationale}}


def review_summary(reviews: Dict[str, Dict[str, Any]], flagged: set) -> str:
    if not reviews:
        return ("Tudo dentro do tom da marca" if not flagged
                else f"{len(flagged)} pauta(s) com alerta: ficam em rascunho para a equipe conferir")
    scores = [r["score"] for r in reviews.values()]
    rewritten = sum(1 for r in reviews.values() if r["rewritten"])
    text = f"Nota média {sum(scores) / len(scores):.1f}/10; {rewritten} de {len(reviews)} reescrita(s) pelo editor"
    return text + (f"; {len(flagged)} em rascunho com alerta" if flagged else "; tudo dentro da marca")


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
    from .studio_intelligence import LIBRARY_RULE, passages_for
    passages = await passages_for(client_id, ask[:400], str(item.get("title") or ""))
    ref_text = "\n".join(f"- {r.get('url')}" + (f" ({r['note']})" if r.get("note") else "") for r in refs[:10])
    prompt = (f"POST ATUAL:\n{json.dumps(current, ensure_ascii=False)}\n\n"
              f"PEDIDO DE AJUSTE DO CLIENTE (atenda exatamente o que ele pediu, sem mudar o resto):\n{ask[:1500]}\n"
              + (f"\nREFERÊNCIAS QUE O CLIENTE MANDOU (links/imagens no estilo que ele quer):\n{ref_text}\n" if ref_text else "")
              + "\nDevolva a nova versão completa: gancho, legenda, roteiro e ideia de imagem (briefing visual para a equipe "
                "produzir a arte). Se o pedido for só sobre a arte, mantenha os textos e reescreva a ideia de imagem. "
                f"Em 'o_que_mudou', uma frase curta para a equipe. {LIBRARY_RULE} Sem travessão. Não invente oferta, preço ou prazo.\n"
              + (f"\nTRECHOS DOS DOCUMENTOS DA MARCA:\n{passages}\n" if passages else "")
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
