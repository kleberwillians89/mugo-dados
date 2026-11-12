"""A IA lê tudo: briefings, planejamentos, eventos, Biblioteca e trechos dos documentos; nada é cortado em silêncio;
e o Editor-chefe da esteira dá nota, reescreve o que é fraco e segura o que nasceu muito fraco."""
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_agents as ag
from services import studio_intelligence as si

TODAY = date(2026, 11, 11)


class PromptTests(unittest.TestCase):
    def test_big_package_is_summarized_not_silently_cut(self):
        pkg = {"marca": {"tom": "leve"}, "briefings_aprovados": [{"titulo": "BF"}],
               "posts": {"lista": [{"t": "a" * 200}] * 80}, "clipping": [{"t": "b" * 400}] * 60}
        data = json.loads(si.to_prompt(pkg, limit=6000))
        self.assertEqual(data["briefings_aprovados"], [{"titulo": "BF"}])  # o que a equipe decidiu fica inteiro
        self.assertIn("clipping", data["_aviso"]["resumidas"])
        self.assertLess(len(data["clipping"]), 60)

    def test_drops_only_after_summarizing_and_says_so(self):
        pkg = {"marca": {"tom": "x" * 3000}, "clipping": "y" * 3000}
        data = json.loads(si.to_prompt(pkg, limit=1500))
        self.assertEqual(data["_aviso"]["omitidas_por_tamanho"], ["clipping"])

    def test_small_package_has_no_warning(self):
        self.assertNotIn("_aviso", si.to_prompt({"marca": {"tom": "leve"}}))

    def test_team_decisions_come_right_after_the_brand(self):
        self.assertEqual(si.PROMPT_ORDER[2:5], ["briefings_aprovados", "planos_aprovados", "referencias_do_cliente"])


class SourcesTests(unittest.IsolatedAsyncioTestCase):
    async def test_plans_keep_strategy_and_upcoming_events(self):
        rows = [{"kind": "planejamento", "title": "Natal", "status": "aprovacao_interna", "inputs": {"objective": "300 kits"},
                 "plan": {"big_idea": "Chega a tempo", "strategy": "Certeza da entrega", "phases": [{"phase": "Venda", "when": "8-20/12", "what": "prova"}],
                          "kpis": [{"kpi": "Kits", "target": "300"}]}},
                {"kind": "evento", "title": "Ativação", "status": "em_andamento", "target_date": "2026-12-10", "inputs": {"location": "Jardins"}, "plan": {}},
                {"kind": "evento", "title": "Antigo", "status": "em_andamento", "target_date": "2026-01-10", "inputs": {}, "plan": {}},
                {"kind": "planejamento", "title": "Sem plano", "status": "fila", "inputs": {}, "plan": {}}]
        with patch.object(si, "sb_select", AsyncMock(return_value=rows)):
            out = await si._plans("ruah", TODAY)
        self.assertEqual([p["titulo"] for p in out["planejamentos"]], ["Natal"])
        self.assertEqual(out["planejamentos"][0]["fases"], ["Venda (8-20/12): prova"])
        self.assertEqual([e["titulo"] for e in out["eventos"]], ["Ativação"])

    async def test_library_by_category_without_links(self):
        rows = [{"kind": "arquivo", "category": "produto", "title": "Oud 10ml.jpg", "mime_type": "image/jpeg", "side": "cliente", "note": "fundo branco"},
                {"kind": "link", "category": "referencia", "title": "Moodboard", "side": "mugo"}]
        with patch.object(si, "sb_select", AsyncMock(return_value=rows)):
            out = await si._library("ruah")
        self.assertEqual(out["produto"], ["Oud 10ml.jpg [image] (do cliente): fundo branco"])
        self.assertEqual(out["referencia"], ["Moodboard [link]"])

    async def test_briefs_bring_what_not_to_do(self):
        rows = [{"brief": {"title": "BF decant", "objective": "Vender", "avoid": ["falar de desconto"], "deliverables": ["4 Reels"]}}]
        with patch.object(si, "sb_select", AsyncMock(return_value=rows)) as sel:
            out = await si._approved_briefs("ruah", TODAY)
        self.assertEqual(out[0]["nao_fazer"], ["falar de desconto"])
        self.assertEqual(sel.await_args.kwargs["filters"]["status"], "in.(pronto,distribuido)")

    async def test_passages_hide_personal_data_and_never_raise(self):
        with patch("services.brand_knowledge.search_chunks", AsyncMock(return_value=[{"content": "Preço do kit R$ 199. Fale com joao@x.com"}])):
            text = await si.passages_for("ruah", "kit natal")
        self.assertIn("R$ 199", text)
        self.assertNotIn("joao@x.com", text)
        with patch("services.brand_knowledge.search_chunks", AsyncMock(side_effect=RuntimeError)):
            self.assertEqual(await si.passages_for("ruah", "kit"), "")


OP = {"id": "o1", "title": "Kit Natal", "hook": "Chegou o Natal", "caption_draft": "Compre já", "format": "reels", "rationale": "Vende muito."}


class EditorTests(unittest.IsolatedAsyncioTestCase):
    async def edit(self, answer):
        saved = {}

        async def update(table, filters, patch):
            saved.update(patch)
            return [{**OP, **patch}]
        with patch.object(ag, "load_profile", AsyncMock(return_value={"profile": {"keywords_avoid": []}})), \
             patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={"marca": {"tom": "leve"}})), \
             patch("services.studio_intelligence.passages_for", AsyncMock(return_value="")), \
             patch("services.studio_llm.llm_json", AsyncMock(return_value=answer)) as llm, \
             patch.object(ag, "sb_update", AsyncMock(side_effect=update)):
            out = await ag.edit_piece("ruah", OP, [{"id": "o1"}, {"id": "o2", "gancho": "Chegou o Natal"}], focus="BF")
        return out, saved, llm

    async def test_good_piece_passes_untouched(self):
        out, saved, llm = await self.edit({"nota": 9, "problemas": [], "gancho": "", "legenda": "", "roteiro": "", "ideia_imagem": ""})
        self.assertFalse(out["rewritten"])
        self.assertEqual(saved["guard"], [])
        self.assertTrue(saved["rationale"].endswith("Editor-chefe: 9/10."))
        prompt = llm.await_args.kwargs["prompt"]
        self.assertIn('"id": "o2"', prompt)  # vê o resto do lote
        self.assertNotIn('"id": "o1"', prompt.split("OUTRAS PEÇAS")[1].split("DADOS")[0])

    async def test_weak_piece_is_rewritten(self):
        out, saved, _ = await self.edit({"nota": 6, "problemas": ["gancho igual ao do lote"], "gancho": "3 perfumes que chegam antes do dia 24",
                                         "legenda": "", "roteiro": "", "ideia_imagem": ""})
        self.assertTrue(out["rewritten"])
        self.assertEqual(saved["hook"], "3 perfumes que chegam antes do dia 24")
        self.assertNotIn("caption_draft", saved)  # campo vazio não apaga o que existe
        self.assertIn("6/10 e reescreveu", saved["rationale"])

    async def test_very_weak_piece_goes_to_the_team(self):
        out, saved, _ = await self.edit({"nota": 3, "problemas": ["inventou preço"], "gancho": "Novo", "legenda": "Nova", "roteiro": "", "ideia_imagem": ""})
        self.assertEqual(saved["guard"][0]["type"], "editor")
        self.assertIn("3/10", saved["guard"][0]["fix"])

    def test_summary(self):
        text = ag.review_summary({"a": {"score": 9, "rewritten": False}, "b": {"score": 7, "rewritten": True}}, set())
        self.assertEqual(text, "Nota média 8.0/10; 1 de 2 reescrita(s) pelo editor; tudo dentro da marca")


if __name__ == "__main__":
    unittest.main()
