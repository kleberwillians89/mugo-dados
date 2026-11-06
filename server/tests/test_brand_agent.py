import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services import brand_agent as ba
from services.studio_calendar import StudioError


def run(coro):
    return asyncio.run(coro)


CHUNKS = [
    {"id": "c1", "document_id": "doc-precos", "content": "Plano mensal R$ 89. Plano anual R$ 790."},
    {"id": "c2", "document_id": "doc-guia", "content": "Tom leve, motivador, sem gírias."},
]


class AgentHarness:
    def __init__(self, reply, past=None, chunks=None):
        self.llm = AsyncMock(return_value=reply)
        self.inserted = []
        self.past = past or []
        self.chunks = CHUNKS if chunks is None else chunks
        self.search = AsyncMock(return_value=self.chunks)

    async def select(self, table, select="*", filters=None, order=None, limit=None, offset=None):
        if table == "clients":
            return [{"id": "m2", "name": "M2 Perfomance"}]
        if table == "brand_documents":
            return [{"id": "doc-precos", "name": "Tabela de preços.xlsx"}, {"id": "doc-guia", "name": "Guia da marca.pdf"}]
        if table == ba.MESSAGES:
            return list(reversed(self.past))[: limit or 40]
        return []

    async def insert(self, table, row, returning="representation"):
        self.inserted.append(row)
        return {"id": f"m{len(self.inserted)}"}

    def ask(self, question="Quanto custa o plano anual?"):
        profile = {"profile": {"tone_of_voice": "Leve e motivador", "pillars": [{"name": "Treino"}, {"name": "Comunidade"}],
                               "keywords_avoid": ["promoção relâmpago"], "audience": ""}}
        context = {"context": {"segment": "Assessoria de corrida", "goals": None}}
        with patch.object(ba, "sb_select", self.select), patch.object(ba, "sb_insert", self.insert), \
             patch("services.brand_knowledge.search_chunks", self.search), \
             patch("services.brand_knowledge.knowledge_for_prompt", AsyncMock(return_value="Empresa: M2\n- Corrida")), \
             patch("services.studio_calendar.load_profile", AsyncMock(return_value=profile)), \
             patch("services.business_context.load_business_context", AsyncMock(return_value=context)), \
             patch("services.studio_engines.throttle", lambda cid: None), \
             patch("services.studio_llm.llm_json", self.llm):
            return run(ba.ask("m2", "user-1", question))


class AskTests(unittest.TestCase):
    def test_answer_with_sources_and_lean_call(self):
        h = AgentHarness({"answer": "O plano anual custa R$ 790.", "on_topic": True, "used_sources": [1, 7], "new_facts": []})
        out = h.ask()
        self.assertEqual(out["answer"], "O plano anual custa R$ 790.")
        self.assertEqual(out["sources"], [{"name": "Tabela de preços.xlsx"}])  # índice 7 não existe: ignorado
        kwargs = h.llm.call_args.kwargs
        self.assertFalse(kwargs["guidance"])
        self.assertEqual(kwargs["max_output_tokens"], ba.MAX_ANSWER_TOKENS)
        self.assertEqual(kwargs["client_id"], "m2")                 # passa pela trava anti-vazamento
        self.assertIn("M2 Perfomance", kwargs["instructions"])
        self.assertIn("SOMENTE sobre esta marca", kwargs["instructions"])
        prompt = kwargs["prompt"]
        self.assertIn("[1] Plano mensal R$ 89", prompt)
        self.assertIn("Pilares: Treino, Comunidade", prompt)
        self.assertIn("Segmento: Assessoria de corrida", prompt)
        self.assertNotIn("Público:", prompt.split("CONTEXTO")[0])  # campo vazio não gasta token
        self.assertLess(len(prompt), 6000)                          # prompt enxuto
        self.assertEqual([r["role"] for r in h.inserted], ["user", "assistant"])

    def test_off_topic_never_suggests_facts(self):
        h = AgentHarness({"answer": "Só falo sobre a M2 Perfomance.", "on_topic": False, "used_sources": [],
                          "new_facts": ["Python é legal"]})
        out = h.ask("Me ensina a programar em Python")
        self.assertFalse(out["on_topic"])
        self.assertEqual(out["new_facts"], [])

    def test_new_facts_are_returned_for_confirmation(self):
        h = AgentHarness({"answer": "Anotado.", "on_topic": True, "used_sources": [],
                          "new_facts": ["A M2 não faz promoção em dezembro", "", "b", "c", "d"]})
        out = h.ask("A M2 não faz promoção em dezembro, beleza?")
        self.assertEqual(out["new_facts"], ["A M2 não faz promoção em dezembro", "b", "c"])
        self.assertEqual(h.inserted[-1]["meta"]["new_facts"], out["new_facts"])

    def test_history_is_short_and_used_for_follow_up_search(self):
        past = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i} " + "x" * 2000} for i in range(20)]
        past[-2] = {"role": "user", "content": "Quanto custa o plano anual?"}
        h = AgentHarness({"answer": "Isso.", "on_topic": True, "used_sources": [], "new_facts": []}, past=past)
        h.ask("E o mensal?")
        prompt = h.llm.call_args.kwargs["prompt"]
        conversation = prompt.split("CONVERSA ANTERIOR:")[1].split("ÚLTIMA MENSAGEM")[0]
        self.assertEqual(conversation.count("Pessoa:") + conversation.count("IA:"), ba.HISTORY_TURNS)
        self.assertLess(len(conversation), ba.HISTORY_TURNS * (ba.HISTORY_CHARS + 20))
        self.assertEqual(h.search.call_args.args[1:3], ("E o mensal?", "Quanto custa o plano anual?"))

    def test_empty_question(self):
        with self.assertRaises(StudioError) as ctx:
            run(ba.ask("m2", "u", "  "))
        self.assertEqual(ctx.exception.code, "AGENT_QUESTION_EMPTY")

    def test_empty_answer_is_an_error(self):
        h = AgentHarness({"answer": "  ", "on_topic": True, "used_sources": [], "new_facts": []})
        with self.assertRaises(StudioError):
            h.ask()

    def test_history_survives_missing_table(self):
        with patch.object(ba, "sb_select", AsyncMock(side_effect=RuntimeError("sem migração"))):
            self.assertEqual(run(ba.history("m2", "u")), [])


class CompactTests(unittest.TestCase):
    def test_profile_only_filled_fields(self):
        text = ba.compact_profile({"tone_of_voice": "Leve", "personality": "", "pillars": [], "keywords_use": ["corrida"]})
        self.assertEqual(text, "Tom de voz: Leve\nPalavras da marca: corrida")

    def test_context_is_capped(self):
        text = ba.compact_context({k: "z" * 2000 for k in ("segment", "product_description", "audience", "positioning",
                                                            "differentiators", "goals")})
        self.assertLessEqual(len(text), ba.CONTEXT_CHARS)


class MigrationTests(unittest.TestCase):
    def body(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "supabase/migrations/20261202_000081_brand_agent.sql"
        return path.read_text(encoding="utf-8").lower()

    def test_new_tables_are_closed_to_the_browser(self):
        body = self.body()
        for table in ("brand_chunks", "brand_agent_messages"):
            self.assertIn(f"alter table public.{table} enable row level security", body)
            self.assertIn(f"revoke all on public.{table} from anon, authenticated", body)
            self.assertIn(f"grant all on public.{table} to service_role", body)
            self.assertLess(body.index(f"revoke all on public.{table}"), body.index("create index"))
        self.assertNotIn("create policy", body)

    def test_search_rpc_is_backend_only_and_scoped(self):
        body = self.body()
        self.assertIn("revoke all on function public.brand_chunk_search(text, text, integer) from public, anon, authenticated", body)
        self.assertIn("grant execute on function public.brand_chunk_search(text, text, integer) to service_role", body)
        self.assertIn("where c.client_id = p_client_id", body)
        self.assertIn("set search_path = public, pg_temp", body)
        self.assertNotIn("security definer", body)

    def test_existing_documents_stay_learned(self):
        self.assertIn("add column if not exists status text not null default 'aprendido'", self.body())


if __name__ == "__main__":
    unittest.main()
