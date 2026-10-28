from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import job_dispatcher as dispatcher  # noqa: E402

UTC = timezone.utc


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class LatestSlotTests(unittest.TestCase):
    def test_slots_match_cron_semantics(self):
        now = at("2026-10-28T17:47:30")
        self.assertEqual(dispatcher.latest_slot("10 6,12,18,23 * * *", now), at("2026-10-28T12:10"))
        self.assertEqual(dispatcher.latest_slot("0,30 * * * *", now), at("2026-10-28T17:30"))
        self.assertEqual(dispatcher.latest_slot("*/10 * * * *", now), at("2026-10-28T17:40"))
        self.assertEqual(dispatcher.latest_slot("20 */3 * * *", now), at("2026-10-28T15:20"))
        # 28/10/2026 é quarta; o domingo anterior é 25/10.
        self.assertEqual(dispatcher.latest_slot("40 8 * * 0", now), at("2026-10-25T08:40"))
        self.assertEqual(dispatcher.latest_slot("10 6,12,18,23 * * *", at("2026-10-28T12:10")), at("2026-10-28T12:10"))

    def test_schedule_is_valid_and_unique(self):
        crons = [job.cron for job in dispatcher.SCHEDULE]
        self.assertEqual(len(crons), len(set(crons)))
        for job in dispatcher.SCHEDULE:
            self.assertIsNotNone(dispatcher.latest_slot(job.cron, at("2026-10-28T12:00")), job.cron)
            self.assertRegex(job.name, r"^[a-z0-9-]+$")


class TickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.started = []
        self.finished = []

        async def start(**kwargs):
            self.started.append(kwargs)
            return {"id": f"run-{len(self.started)}"}

        async def finish(run_id, **kwargs):
            self.finished.append((run_id, kwargs))

        self.patches = [patch.object(dispatcher, "start_job_run", start), patch.object(dispatcher, "finish_job_run", finish)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    async def tick(self, last_runs, runner=None, budget=600, now="2026-10-28T17:47"):
        async def select(table, *, select, filters, order, limit):
            key = filters["job_name"][3:]
            value = last_runs.get(key)
            return [{"started_at": value}] if value else []

        ran, lines = [], []

        async def default_runner(command):
            ran.append(command)
            return {"ok": True, "connections_total": 2, "connections_ok": 2, "connections_fail": 0}

        with patch.object(dispatcher, "sb_select", select):
            result = await dispatcher.run_tick(runner or default_runner, budget_seconds=budget, now=at(now), emit=lines.append)
        return result, ran, lines

    async def test_missed_slots_are_recovered_by_any_surviving_tick(self):
        # Cenário real: o horário das 12:10 do orgânico foi descartado pelo GitHub.
        everything_current = {job.key: "2026-10-28T17:46:00+00:00" for job in dispatcher.SCHEDULE}
        everything_current[dispatcher.JOB_PREFIX + "organic-sync --limit 60"] = "2026-10-28T06:12:00+00:00"
        result, ran, lines = await self.tick(everything_current)
        self.assertEqual(ran, ["organic-sync --limit 60"])
        self.assertTrue(result["ok"])
        self.assertEqual(lines, ["[tick] job=organic-sync status=ok duracao_s=0 falhas=0/2"])
        self.assertEqual(self.started[0]["job_name"], "dispatcher:organic-sync --limit 60")
        self.assertEqual(self.finished[0][1]["status"], "success")

    async def test_nothing_runs_twice_for_the_same_slot(self):
        current = {job.key: "2026-10-28T17:47:00+00:00" for job in dispatcher.SCHEDULE}
        result, ran, _ = await self.tick(current)
        self.assertEqual(ran, [])
        self.assertEqual(result["due"], 0)

    async def test_first_run_ever_runs_everything_in_priority_order(self):
        _, ran, _ = await self.tick({})
        self.assertEqual(ran, [job.command for job in dispatcher.SCHEDULE])
        self.assertEqual(ran[0], "token-refresh")

    async def test_partial_failure_and_crash_are_recorded_without_stopping_the_tick(self):
        async def runner(command):
            if command.startswith("organic-sync"):
                return {"ok": False, "connections_total": 5, "connections_ok": 4, "connections_fail": 1}
            if command.startswith("ga4"):
                raise RuntimeError("token inválido do cliente X")
            return {"ok": True}

        result, _, lines = await self.tick({}, runner=runner)
        self.assertFalse(result["ok"])  # exceção faz o workflow ficar vermelho
        self.assertIn("[tick] job=organic-sync status=parcial duracao_s=0 falhas=1/5", lines)
        self.assertIn("[tick] job=ga4-sync-all status=falhou duracao_s=0", lines)
        self.assertFalse(any("inválido" in line or "cliente X" in line for line in lines))
        statuses = {self.started[int(run_id.split("-")[1]) - 1]["payload_json"]["command"]: kw["status"] for run_id, kw in self.finished}
        self.assertEqual(statuses["organic-sync --limit 60"], "partial")
        self.assertEqual(statuses["ga4-sync-all --days 3"], "error")
        self.assertEqual(statuses["token-refresh"], "success")

    async def test_hung_job_times_out_and_budget_defers_the_rest(self):
        async def runner(command):
            await asyncio.sleep(10)

        with patch.object(dispatcher, "SCHEDULE", (dispatcher.ScheduledJob("*/5 * * * *", "fbits-sync-all", 0),
                                                   dispatcher.ScheduledJob("*/10 * * * *", "ads-backfill-worker", 0))):
            result, _, lines = await self.tick({}, runner=runner, budget=0)
        self.assertEqual(lines, ["[tick] job=fbits-sync-all status=adiado duracao_s=0",
                                 "[tick] job=ads-backfill-worker status=adiado duracao_s=0"])
        self.assertTrue(result["ok"])

        with patch.object(dispatcher, "SCHEDULE", (dispatcher.ScheduledJob("*/5 * * * *", "fbits-sync-all", 0),)):
            result, _, lines = await self.tick({}, runner=runner)
        self.assertEqual(lines, ["[tick] job=fbits-sync-all status=tempo_esgotado duracao_s=0"])
        self.assertFalse(result["ok"])

    async def test_unreadable_history_still_runs_and_unrecordable_start_still_runs(self):
        async def broken_select(*args, **kwargs):
            raise RuntimeError("supabase fora")

        async def broken_start(**kwargs):
            raise RuntimeError("insert falhou")

        ran = []

        async def runner(command):
            ran.append(command)
            return {"ok": True}

        with patch.object(dispatcher, "sb_select", broken_select), patch.object(dispatcher, "start_job_run", broken_start), \
             patch.object(dispatcher, "SCHEDULE", (dispatcher.ScheduledJob("*/5 * * * *", "fbits-sync-all", 1),)):
            result = await dispatcher.run_tick(runner, budget_seconds=60, now=at("2026-10-28T17:47"), emit=lambda _: None)
        self.assertEqual(ran, ["fbits-sync-all"])
        self.assertTrue(result["ok"])


class RunJobsWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_tick_dispatches_real_run_jobs_commands(self):
        import run_jobs

        parser = run_jobs._build_parser()
        for job in dispatcher.SCHEDULE:
            with self.subTest(command=job.command):
                parser.parse_args(job.command.split())  # todo comando da agenda existe no CLI

        captured = {}

        async def fake_tick(runner, *, budget_seconds):
            captured["budget"] = budget_seconds
            with patch.object(run_jobs, "run_daily_instagram_sync", AsyncMock(return_value={"ok": True})) as organic:
                await runner("organic-sync --limit 60")
            captured["organic"] = organic.await_args.kwargs
            return {"ok": True}

        with patch("services.job_dispatcher.run_tick", fake_tick):
            await run_jobs._run(parser.parse_args(["tick", "--budget-minutes", "40"]))
        self.assertEqual(captured["budget"], 2400)
        self.assertEqual(captured["organic"], {"limit": 60, "process_thumbnails": True})


if __name__ == "__main__":
    unittest.main()
