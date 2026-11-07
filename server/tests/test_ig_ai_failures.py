"""IA dos comentários: falha nunca mais é silenciosa (motivo gravado, resumo da rodada, alerta no GitHub)."""
import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from services import ig_engagement as ie
from services import studio_llm
from services.studio_calendar import StudioError


def run(coro):
    return asyncio.run(coro)


NOW = datetime.now(timezone.utc).isoformat()
COMMENTS = [{"comment_id": "1111111", "media_id": "m1", "username": "ana", "text": "Que lindo!", "timestamp": NOW},
            {"comment_id": "2222222", "media_id": "m1", "username": "bia", "text": "Amei 🔥", "timestamp": NOW}]
CREDS = {"token": "t", "username": "marca", "scopes": ["instagram_manage_comments"]}


class Harness:
    def __init__(self, answer):
        self.answer = answer
        self.inserted = []
        self.updated = []

    async def insert(self, table, row, returning="representation"):
        self.inserted.append(row)
        return {"id": f"a{len(self.inserted)}"}

    async def update(self, table, *, filters, patch, returning="representation"):
        self.updated.append(patch)
        return []

    def go(self, settings=None, creds=CREDS):
        with patch.object(ie, "get_settings", AsyncMock(return_value=settings or {"ai_autoreply": True, "max_per_run": 10})), \
             patch.object(ie, "_ai_answer", self.answer), patch.object(ie, "sb_insert", self.insert), \
             patch.object(ie, "sb_update", self.update):
            return run(ie.run_ai_replies("lat", creds=creds, comments=COMMENTS, handled=set(), budget=30))


class ProviderDetailTests(unittest.TestCase):
    def test_status_and_code_only(self):
        resp = MagicMock(status_code=429)
        resp.json.return_value = {"error": {"code": "insufficient_quota", "message": "texto longo com dados"}}
        self.assertEqual(studio_llm.provider_error_detail(resp), "http_429:insufficient_quota")
        bad = MagicMock(status_code=500)
        bad.json.side_effect = ValueError("not json")
        self.assertEqual(studio_llm.provider_error_detail(bad), "http_500")

    def test_reasons_are_actionable(self):
        self.assertIn("sem crédito", ie.failure_reason("AI_PROVIDER_ERROR", "http_429:insufficient_quota"))
        self.assertIn("Chave da OpenAI inválida", ie.failure_reason("AI_PROVIDER_ERROR", "http_401"))
        self.assertIn("não está configurada", ie.failure_reason("AI_PROVIDER_NOT_CONFIGURED"))
        self.assertEqual(ie.failure_reason("AI_PROVIDER_ERROR", "http_503"), "A OpenAI recusou o pedido. (http_503)")


class FailureRecordingTests(unittest.TestCase):
    def test_ai_failure_is_recorded_with_reason(self):
        h = Harness(AsyncMock(side_effect=StudioError("AI_PROVIDER_ERROR", "http_429:insufficient_quota")))
        out = h.go()
        self.assertEqual(out["ai_failed"], 2)
        self.assertEqual(out["ai_errors"], {"AI_PROVIDER_ERROR:http_429:insufficient_quota": 2})
        self.assertEqual([r["status"] for r in h.inserted], ["falhou", "falhou"])  # não bloqueia nova tentativa
        self.assertIn("sem crédito", h.inserted[0]["text"])
        self.assertEqual(h.inserted[0]["error"], "AI_PROVIDER_ERROR:http_429:insufficient_quota")

    def test_success_still_works(self):
        h = Harness(AsyncMock(return_value={"reply": "Obrigada! 💛", "needs_human": False, "reason": "", "guard": []}))
        out = h.go()
        self.assertEqual(out["ai_simulated"], 2)
        self.assertEqual(out["ai_failed"], 0)
        self.assertEqual(out["ai_candidates"], 2)

    def test_skips_say_why(self):
        self.assertEqual(Harness(AsyncMock()).go(settings={"ai_autoreply": False, "max_per_run": 10})["ai_skipped"], "ia_desligada")
        self.assertEqual(Harness(AsyncMock()).go(creds={**CREDS, "scopes": {"instagram_basic"}})["ai_skipped"], "sem_permissao_responder")


class SummaryTests(unittest.TestCase):
    def test_status(self):
        self.assertEqual(ie.run_status({"ai_failed": 3}), "error")
        self.assertEqual(ie.run_status({"ai_failed": 1, "ai_sent": 2}), "partial")
        self.assertEqual(ie.run_status({"ai_sent": 2}), "success")
        self.assertEqual(ie.run_status({}), "success")
        self.assertEqual(ie.run_status({"ai_skipped": "ia_desligada"}), "skipped")
        self.assertEqual(ie.run_status({"error": "META_TOKEN_EXPIRED"}), "error")

    def test_summary_text(self):
        self.assertEqual(ie.run_summary({"ai_sent": 3, "ai_review": 1}), "3 publicada(s), 1 para revisão.")
        self.assertEqual(ie.run_summary({}), "Nenhum comentário novo sem resposta nos últimos 3 dias.")
        text = ie.run_summary({"ai_failed": 4, "ai_errors": {"AI_PROVIDER_ERROR:http_429:insufficient_quota": 4}})
        self.assertIn("4 com falha", text)
        self.assertIn("sem crédito", text)
        self.assertIn("Instagram recusou", ie.run_summary({"ai_failed": 1, "ai_errors": {"INSTAGRAM:IG_TOKEN_INVALID": 1}}))
        self.assertIn("permissão", ie.run_summary({"ai_skipped": "sem_permissao_responder"}))


class RunAllTests(unittest.TestCase):
    def _run_all(self, results):
        recorded = []

        async def fake_rules(cid, ai=False):
            res = results[cid]
            if isinstance(res, Exception):
                raise res
            return res

        async def fake_record(cid, result, started):
            recorded.append((cid, ie.run_status(result)))
        with patch.object(ie, "sb_select", AsyncMock(side_effect=[[], [{"client_id": c} for c in results]])), \
             patch.object(ie, "run_rules", fake_rules), patch.object(ie, "_record_run", fake_record), \
             patch.object(ie, "_ai_on", AsyncMock(return_value=True)):
            out = run(ie.run_all(ai=True))
        return out, recorded

    def test_each_brand_with_ai_gets_a_record_and_failures_are_counted(self):
        out, recorded = self._run_all({
            "lat": {"ai_on": True, "ai_failed": 2, "ai_candidates": 2},
            "m2": {"ai_on": True, "ai_sent": 3, "ai_candidates": 3},
            "cura": {"ai_on": False, "rules": 1},
            "ruah": RuntimeError("meta fora"),
        })
        self.assertEqual(sorted(recorded), [("lat", "error"), ("m2", "success"), ("ruah", "error")])
        self.assertEqual(out["ai_brands_failed"], 2)

    def test_job_exits_with_error_when_a_brand_failed(self):
        import run_jobs
        args = MagicMock(command="ig-ai-replies")
        with patch.object(run_jobs, "_build_parser") as parser, \
             patch.object(run_jobs, "_run", AsyncMock(return_value={"ai_brands_failed": 1})), \
             patch.object(run_jobs, "_print_json"):
            parser.return_value.parse_args.return_value = args
            with self.assertRaises(SystemExit):
                run_jobs.main()
            run_jobs._run.return_value = {"ai_brands_failed": 0}
            run_jobs.main()  # sem falha: termina normal


class LastRunTests(unittest.TestCase):
    def test_last_run_for_the_screen(self):
        row = {"started_at": "2026-11-07T19:00:30Z", "finished_at": "2026-11-07T19:01:20Z", "status": "error",
               "payload_json": {"summary": "4 com falha. Motivo: Conta da OpenAI sem crédito.", "ai_failed": 4, "live": True}}
        with patch.object(ie, "sb_select", AsyncMock(return_value=[row])):
            out = run(ie.last_ai_run("lat"))
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["counts"]["ai_failed"], 4)
        self.assertIn("sem crédito", out["summary"])
        with patch.object(ie, "sb_select", AsyncMock(side_effect=RuntimeError("x"))):
            self.assertIsNone(run(ie.last_ai_run("lat")))


if __name__ == "__main__":
    unittest.main()
