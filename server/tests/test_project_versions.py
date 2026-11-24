"""Versões do Planejamento: refazer com IA, aprovar e restaurar nunca apagam o plano anterior."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import studio_project_versions as spv  # noqa: E402
from services import studio_projects as sp  # noqa: E402
from services.studio_calendar import StudioError  # noqa: E402

PLAN_V1 = {"big_idea": "Natal perfumado", "strategy": "Presentes", "phases": []}
PROJECT = {"id": "p1", "kind": "planejamento", "title": "Natal", "status": "em_andamento", "inputs": {"objective": "Vender kits"},
           "plan": PLAN_V1, "chat": []}
AI = {"contexto": "c", "desafio": "d", "insight": "i", "estrategia": "Nova estratégia", "grande_ideia": "Natal 2", "mensagens": [],
      "canais": [], "fases": [], "kpis": [], "riscos": []}


class Store:
    """Tabela de versões em memória."""
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    async def select(self, table, select="*", filters=None, order=None, limit=None):
        assert table == spv.TABLE
        rows = [r for r in self.rows if r["project_id"] == filters["project_id"][3:]]
        if "version" in filters:
            rows = [r for r in rows if r["version"] == int(filters["version"][3:])]
        if "client_id" in filters:
            rows = [r for r in rows if r["client_id"] == filters["client_id"][3:]]
        return sorted(rows, key=lambda r: -r["version"])[: limit or 100]

    async def insert(self, table, row, returning=None):
        if any(r["project_id"] == row["project_id"] and r["version"] == row["version"] for r in self.rows):
            raise RuntimeError("duplicate")
        self.rows.append({**row, "created_at": "2026-11-24T20:00:00Z"})


def broken(*a, **k):
    raise RuntimeError("relation studio_project_versions does not exist")


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_numbers_grow_and_identical_content_is_not_duplicated(self):
        store = Store()
        with patch.object(spv, "sb_select", store.select), patch.object(spv, "sb_insert", store.insert):
            self.assertEqual(await spv.snapshot("ruah", PROJECT, origin="ia", user_id="u1", user_name="Kleber"), 1)
            self.assertEqual(await spv.snapshot("ruah", PROJECT, origin="edicao", user_id="u1", user_name="Kleber"), 1)
            self.assertEqual(await spv.snapshot("ruah", {**PROJECT, "plan": {"big_idea": "outra"}}, origin="edicao", user_id="u2", user_name="Julia"), 2)
            listed = await spv.list_versions("ruah", "p1")
            other = await spv.list_versions("outra-marca", "p1")
        self.assertEqual([(v["version"], v["author"], v["origin_label"]) for v in listed],
                         [(2, "Julia", "Edição da equipe"), (1, "Kleber", "Gerada pela IA")])
        self.assertEqual(other, [])  # versões de outra empresa não aparecem

    async def test_project_without_plan_has_no_version(self):
        with patch.object(spv, "sb_select", AsyncMock(return_value=[])), patch.object(spv, "sb_insert", AsyncMock()) as ins:
            self.assertIsNone(await spv.snapshot("ruah", {**PROJECT, "plan": {"research": {}}}, origin="ia", user_id=None, user_name=None))
        ins.assert_not_awaited()


class GenerateTests(unittest.IsolatedAsyncioTestCase):
    async def run_generate(self, store, project=PROJECT, select=None):
        llm = AsyncMock(return_value=AI)
        with patch.object(sp, "get_project", AsyncMock(return_value=project)), patch.object(sp, "load_profile", AsyncMock(return_value={"profile": {}})), \
             patch("services.studio_engines.throttle"), patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={})), \
             patch("services.studio_intelligence.to_prompt", return_value="{}"), \
             patch.object(sp, "project_research", AsyncMock(return_value={"items": [], "selected": []})), \
             patch("services.studio_llm.llm_json", llm), \
             patch.object(sp, "sb_update", AsyncMock(side_effect=lambda t, filters, patch: [{**project, **patch}])) as upd, \
             patch.object(spv, "sb_select", select or store.select), patch.object(spv, "sb_insert", store.insert):
            out = await sp.generate_plan("ruah", "p1", instruction="mais Black Friday", user_id="u1", user_name="Kleber")
        return out, upd, llm

    async def test_redo_keeps_previous_plan_and_records_new_version(self):
        store = Store()
        out, _, _ = await self.run_generate(store)
        self.assertEqual(out["plan"]["strategy"], "Nova estratégia")
        versions = sorted(store.rows, key=lambda r: r["version"])
        self.assertEqual([(v["version"], v["origin"]) for v in versions], [(1, "ia"), (2, "ia")])
        self.assertEqual(versions[0]["plan"], PLAN_V1)           # a anterior fica inteira
        self.assertEqual(versions[1]["plan"]["strategy"], "Nova estratégia")
        self.assertEqual(versions[1]["note"], "mais Black Friday")
        self.assertEqual(versions[1]["created_by_name"], "Kleber")

    async def test_manual_edit_after_last_version_is_kept_as_edit(self):
        store = Store([{"client_id": "ruah", "project_id": "p1", "version": 1, "origin": "ia", "plan": {"big_idea": "antes"}, "inputs": {}}])
        await self.run_generate(store)
        self.assertEqual([(r["version"], r["origin"]) for r in sorted(store.rows, key=lambda r: r["version"])],
                         [(1, "ia"), (2, "edicao"), (3, "ia")])

    async def test_without_versions_table_the_plan_is_not_replaced(self):
        with self.assertRaises(StudioError) as ctx:
            await self.run_generate(Store(), select=AsyncMock(side_effect=broken))
        self.assertEqual(ctx.exception.code, "PROJECT_VERSIONS_UNAVAILABLE")

    async def test_first_generation_works_without_versions_table(self):
        out, _, _ = await self.run_generate(Store(), project={**PROJECT, "plan": {}}, select=AsyncMock(side_effect=broken))
        self.assertEqual(out["plan"]["strategy"], "Nova estratégia")


class ApproveAndRestoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_approval_records_approved_version(self):
        store = Store([{"client_id": "ruah", "project_id": "p1", "version": 1, "origin": "ia", "plan": PLAN_V1, "inputs": PROJECT["inputs"]}])
        with patch.object(sp, "get_project", AsyncMock(return_value=PROJECT)), \
             patch.object(sp, "sb_update", AsyncMock(side_effect=lambda t, filters, patch: [{**PROJECT, **patch}])), \
             patch.object(spv, "sb_select", store.select), patch.object(spv, "sb_insert", store.insert):
            await sp.update_project("ruah", "p1", {"status": "finalizado"}, user_id="u1", user_name="Danilo")
        last = max(store.rows, key=lambda r: r["version"])
        self.assertEqual((last["version"], last["origin"], last["created_by_name"]), (2, "aprovada", "Danilo"))

    async def test_restore_keeps_current_and_creates_new_version_with_old_content(self):
        current = {**PROJECT, "plan": {"big_idea": "atual"}}
        store = Store([{"client_id": "ruah", "project_id": "p1", "version": 1, "origin": "ia", "plan": PLAN_V1, "inputs": PROJECT["inputs"],
                        "title": "Natal", "status": "em_andamento"}])
        with patch.object(sp, "get_project", AsyncMock(return_value=current)), \
             patch.object(sp, "sb_update", AsyncMock(side_effect=lambda t, filters, patch: [{**current, **patch}])), \
             patch.object(spv, "sb_select", store.select), patch.object(spv, "sb_insert", store.insert):
            out = await sp.restore_version("ruah", "p1", 1, user_id="u1", user_name="Kleber")
        self.assertEqual(out["plan"], PLAN_V1)
        rows = sorted(store.rows, key=lambda r: r["version"])
        self.assertEqual([(r["version"], r["origin"]) for r in rows], [(1, "ia"), (2, "edicao"), (3, "restaurada")])
        self.assertEqual(rows[1]["plan"], {"big_idea": "atual"})
        self.assertEqual(rows[2]["note"], "Conteúdo da versão 1")

    async def test_restore_unknown_version(self):
        with patch.object(sp, "get_project", AsyncMock(return_value=PROJECT)), patch.object(spv, "sb_select", Store().select):
            with self.assertRaises(StudioError) as ctx:
                await sp.restore_version("ruah", "p1", 9, user_id="u1", user_name="K")
        self.assertEqual(ctx.exception.code, "PROJECT_VERSION_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
