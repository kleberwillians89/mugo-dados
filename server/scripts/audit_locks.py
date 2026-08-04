from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.audit_supabase import ReadOnlySupabase
from services.lock_audit import inspect_lock_infrastructure, remediation_sql


async def main() -> int:
    client = ReadOnlySupabase()
    report = await inspect_lock_infrastructure(client, PROJECT_DIR / "supabase" / "migrations")
    output_dir = Path.cwd() / "audit-output"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "lock-infrastructure-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if report["missing"] or report["source_missing"]:
        (output_dir / "locks-remediation.sql").write_text(remediation_sql(), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "read_only": True, "missing": report["missing"]}, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
