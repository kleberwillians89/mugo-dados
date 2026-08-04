from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.audit_supabase import ReadOnlySupabase
from services.data_audit import assert_report_has_no_secrets, audit_existing_connections


async def main() -> int:
    client = ReadOnlySupabase()
    report = await audit_existing_connections(client.select)
    client.assert_read_only()
    assert_report_has_no_secrets(report)
    report["transport"] = {
        "methods": sorted({item["method"] for item in client.request_log}),
        "request_count": len(client.request_log),
    }
    output_dir = Path.cwd() / "audit-output"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "audit-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "audit-report.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["severity", "code", "client_id", "provider", "connection_id", "safe_reason", "suggested_action", "table", "count"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["issues"])
    print(json.dumps({"ok": True, "dry_run": True, "summary": report["summary"], "output_dir": str(output_dir)}, ensure_ascii=False))
    return 2 if report["summary"]["critical"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
