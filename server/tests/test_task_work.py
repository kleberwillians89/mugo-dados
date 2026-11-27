"""Kanban → produção (Black November): seletor, leitor de contexto, e-mail ligado à tarefa, isolamento."""
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import email_from_task as eft  # noqa: E402
from services import task_context as tc  # noqa: E402
from services.studio_calendar import StudioError  # noqa: E402

TASK = "11111111-2222-3333-4444-555555555555"
OTHER_TASK = "99999999-2222-3333-4444-555555555555"
BRIEF = "aaaaaaaa-2222-3333-4444-555555555555"
ME = "12345678-1234-1234-1234-123456789012"
TEAM = {"client_view": False, "team": True, "only_user": None}

BLACK = {"id": BRIEF, "tasks": [{"task_id": TASK, "role": "redator"}], "brief": {
    "title": "Black November: até 50% off em vinhos", "summary": "Campanha promocional em novembro.",
    "objective": "Aumentar pedidos e faturamento", "key_message": "Até 50% off em vinhos naturais e orgânicos",
    "audience": "Interessados em vinhos naturais e orgânicos", "goal": "+30% de pedidos", "deadline": "2026-11-30",
    "deliverables": ["E-mails promocionais", "Texto da landing page", "Legendas", "Reels", "Campanha Google Ads Shopping"],
    "avoid": ["Não prometer descontos superiores a 50%", "Não usar linguagem técnica"],
    "roles": [{"role": "redator", "what": "Produzir textos para e-mails, landing page e legendas"}]}}


def task_row(**extra):
    return {"id": TASK, "client_id": "curavino", "title": "Redator: Black November", "status": "pending",
            "notes": "Briefing: Black November", "assignee_user_ids": [ME], "assignee_names": ["Ana"],
            "visible_to_client": False, "category": "Redator", **extra}


class Fake:
    def __init__(self, task=None, brief=BLACK, links=None, campaigns=None):
        self.task, self.brief, self.links, self.campaigns = task or task_row(), brief, links or [], campaigns or []
        self.inserts = []
        self.brief_filters = None
        self.claim = None

    async def select(self, table, select=None, filters=None, **_):
        filters = filters or {}
        if table == "studio_tasks":
            ok = filters.get("client_id") == f"eq.{self.task['client_id']}" and filters.get("id") == f"eq.{self.task['id']}"
            return [self.task] if ok else []
        if table == "studio_briefs":
            self.brief_filters = filters
            return [self.brief] if self.brief and filters.get("client_id") == "eq.curavino" else []
        if table == "task_work_links":
            return [l for l in self.links if filters.get("client_id") == f"eq.{l['client_id']}"]
        if table == "email_campaigns":
            return [c for c in self.campaigns if filters.get("client_id") == "eq.curavino"]
        if table == "clients":
            return [{"name": "Curavino"}]
        return []

    async def insert(self, table, row, **_):
        self.inserts.append((table, row))

    async def rpc(self, name, args):
        if name == "claim_task_work_link":
            self.claim = args
            return [{"link_id": "link-1", "link_status": "pending", "record_id": None, "acquired": True}]
        if name == "complete_task_work_link":
            row = {"client_id": self.claim["p_client_id"], "task_id": self.claim["p_task_id"],
                   "brief_id": self.claim["p_brief_id"], "module": self.claim["p_module"],
                   "deliverable": self.claim["p_deliverable"], "record_id": args["p_record_id"],
                   "operation_key": self.claim["p_operation_key"]}
            self.inserts.append(("task_work_links", row))
            return {**row, "id": "link-1", "link_status": "linked"}
        if name == "fail_task_work_link":
            return None
        raise AssertionError(name)


def patched(fake):
    return [patch.object(tc, "sb_select", fake.select), patch.object(tc, "sb_rpc", fake.rpc),
            patch("services.ig_supabase.sb_select", fake.select)]


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def ctx(self, fake, scope=TEAM, module="email_marketing", client="curavino", task=TASK):
        ps = patched(fake)
        for p in ps:
            p.start()
        try:
            return await tc.task_context(client, task, scope, module=module)
        finally:
            for p in ps:
                p.stop()

    async def test_black_november_context_is_structured_from_the_brief(self):
        fake = Fake()
        out = await self.ctx(fake)
        c = out["context"]
        self.assertEqual(out["client_name"], "Curavino")
        self.assertEqual(out["source"], "briefing")
        self.assertEqual(c["objective"], "Aumentar pedidos e faturamento")
        self.assertIn("Não prometer descontos superiores a 50%", c["avoid"])
        self.assertEqual(c["your_part"], "Produzir textos para e-mails, landing page e legendas")
        self.assertEqual(out["deliverables_for_module"], ["E-mails promocionais"])
        self.assertEqual(out["suggested_deliverable"], "E-mails promocionais")
        self.assertEqual(json.loads(fake.brief_filters["tasks"][3:]), [{"task_id": TASK}])

    async def test_each_module_sees_its_own_deliverables(self):
        d = BLACK["brief"]["deliverables"]
        self.assertEqual(tc.deliverables_for("social_media", d), ["Legendas", "Reels"])
        self.assertEqual(tc.deliverables_for("midia_on", d), ["Campanha Google Ads Shopping"])
        self.assertEqual(tc.deliverables_for("redacao", d), ["Texto da landing page"])

    async def test_task_without_brief_reads_labelled_notes(self):
        notes = "Pedido do cliente\nObjetivo: vender mais\nNão fazer: prometer frete grátis; citar concorrentes\nEntregáveis: E-mail; Post"
        out = await self.ctx(Fake(task=task_row(notes=notes), brief=None))
        self.assertEqual(out["source"], "notas")
        self.assertEqual(out["context"]["objective"], "vender mais")
        self.assertEqual(out["context"]["avoid"], ["prometer frete grátis", "citar concorrentes"])
        self.assertEqual(out["deliverables_for_module"], ["E-mail"])

    async def test_tenant_and_scope_isolation(self):
        with self.assertRaises(StudioError):  # outra empresa: não encontrada
            await self.ctx(Fake(), client="ruah")
        with self.assertRaises(StudioError):  # só vê as dele e não é dele
            await self.ctx(Fake(task=task_row(assignee_user_ids=["outro"], created_by="outro")),
                           scope={"client_view": False, "team": False, "only_user": ME})
        with self.assertRaises(StudioError):  # cliente: tarefa interna não aparece
            await self.ctx(Fake(), scope={"client_view": True, "team": False, "only_user": None})
        with self.assertRaises(StudioError):  # id inválido não chega ao banco
            await self.ctx(Fake(), task="'; drop")

    def test_offer_limit_is_read_from_restrictions(self):
        self.assertEqual(tc.max_percent_allowed(["Não prometer descontos superiores a 50%"]), 50)
        self.assertEqual(tc.percents_over("Até 50% off, e 70% no segundo", 50), [70])
        self.assertEqual(tc.percents_over("Até 50% off", 50), [])
        self.assertIsNone(tc.max_percent_allowed(["sem jargão"]))


class EmailFromTaskTests(unittest.IsolatedAsyncioTestCase):
    async def run_create(self, fake, llm=None, **kwargs):
        save = AsyncMock(side_effect=lambda cid, body, user_id: {"id": "c-new", "name": body.get("name"), "status": "rascunho", **body})
        llm = llm or AsyncMock(return_value={"assunto": "Até 50% off em vinhos naturais", "preheader": "Só em novembro",
                                             "titulo": "Black November", "texto": "Parágrafo 1\n\nParágrafo 2",
                                             "botao": "Ver vinhos", "fotos": ["taça de vinho"]})
        ps = patched(fake) + [patch("services.email_marketing.save_campaign", save), patch("services.studio_llm.llm_json", llm),
                              patch("services.email_brand_look.ensure_brand_look", AsyncMock(return_value={})),
                              patch("services.email_brand_look.library_photos", AsyncMock(return_value=[]))]
        for p in ps:
            p.start()
        try:
            out = await eft.create_from_task("curavino", TASK, TEAM, user_id=ME, **kwargs)
        finally:
            for p in ps:
                p.stop()
        return out, save, llm

    async def test_creates_a_draft_linked_to_the_task(self):
        fake = Fake()
        out, save, llm = await self.run_create(fake)
        self.assertEqual(out["created"]["status"], "rascunho")
        body = save.await_args.args[1]
        self.assertEqual(body["subject"], "Até 50% off em vinhos naturais")
        self.assertNotIn("status", body)  # nunca agenda nem envia
        self.assertEqual(fake.inserts[0][0], "task_work_links")
        link = fake.inserts[0][1]
        self.assertEqual((link["task_id"], link["module"], link["record_id"], link["deliverable"], link["brief_id"]),
                         (TASK, "email_marketing", "c-new", "E-mails promocionais", BRIEF))
        prompt = llm.await_args.kwargs["prompt"]
        self.assertIn("Restrições (obrigatórias): Não prometer descontos superiores a 50%", prompt)
        self.assertIn("só este): E-mails promocionais", prompt)
        self.assertIn("desconto maior que 50%", llm.await_args.kwargs["instructions"])
        self.assertEqual(llm.await_args.kwargs["client_id"], "curavino")

    async def test_existing_draft_is_offered_instead_of_duplicating(self):
        fake = Fake(links=[{"client_id": "curavino", "record_id": "c-old", "deliverable": "E-mails promocionais"}],
                    campaigns=[{"id": "c-old", "name": "Black", "status": "rascunho"}])
        out, save, llm = await self.run_create(fake)
        self.assertIsNone(out["created"])
        self.assertEqual(out["existing"][0]["id"], "c-old")
        save.assert_not_awaited()
        llm.assert_not_awaited()
        out, save, _ = await self.run_create(fake, new_version=True)
        self.assertEqual(out["created"]["id"], "c-new")

    async def test_offer_above_limit_is_retried_then_refused(self):
        bad = AsyncMock(return_value={"assunto": "70% off!", "texto": "", "titulo": "", "preheader": "", "botao": "", "fotos": []})
        with self.assertRaises(StudioError) as ctx:
            await self.run_create(Fake(), llm=bad)
        self.assertEqual(ctx.exception.code, "EMAIL_OFFER_OVER_LIMIT")
        self.assertEqual(bad.await_count, 2)
        self.assertIn("70%", bad.await_args.kwargs["instructions"])

    async def test_blank_mode_needs_no_ai(self):
        out, save, llm = await self.run_create(Fake(), mode="branco")
        llm.assert_not_awaited()
        self.assertEqual(save.await_args.args[1], {"name": "Redator: Black November · E-mails promocionais"})


class RouteTests(unittest.TestCase):
    def test_reading_the_task_does_not_grant_email_creation(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from routes import task_work
        app = FastAPI(); app.include_router(task_work.router)
        client = TestClient(app)
        create = AsyncMock()
        denied = AsyncMock(side_effect=HTTPException(status_code=403, detail="Sem permissão"))
        with patch.object(task_work, "_scope", AsyncMock(return_value=("curavino", TEAM))), \
                patch.object(task_work, "require_client_role", denied), \
                patch.object(task_work.email_from_task, "create_from_task", create):
            r = client.post(f"/api/clients/curavino/crm/work/tasks/{TASK}/email", json={}, headers={"Authorization": "Bearer x"})
        self.assertEqual(r.status_code, 403)
        create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
