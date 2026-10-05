"""Mutação em cópias temporárias; nunca copia .env ou altera fontes originais."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BACK = [
    ("FBITS provider", "services/provider_refresh.py", "await sync_fbits_connection(client_id=client_id)", "pass"),
    ("FBITS persistência", "services/fbits_connections.py", 'await sb_upsert("fbits_orders", order_rows, on_conflict="client_id,order_id")', "pass"),
    ("FBITS invalidation", "services/provider_refresh.py", "await invalidate_official_kpis(client_id)", "pass"),
    ("FBITS freshness", "services/fbits_connections.py", 'metadata["last_success_at"] = _iso(finished)', "pass"),
    ("Meta provider", "services/instagram_sync.py", "profile = await fetch_profile(ig_user_id, access_token)", "profile = {}"),
    ("Meta persistência", "services/instagram_sync.py", "await sb_upsert(", "await _skip_upsert("),
    ("Meta freshness/projeção", "services/instagram_sync.py", "read_model_result = await refresh_dashboard_read_model_safely(", "read_model_result = await _skip_upsert("),
]
FRONT = [
    ("FBITS releitura antes do sync", "src/pages/Ecommerce.tsx", "      await runExclusiveSync(", "      void runExclusiveSync("),
    ("FBITS admin releitura antes do sync", "src/components/FbitsIntegrationPanel.tsx", "      await runExclusiveSync(", "      void runExclusiveSync("),
    ("Meta releitura antes do sync", "src/pages/Dashboard.tsx", "      await runExclusiveSync(\n", "      void runExclusiveSync(\n"),
    ("Meta resumo antigo", "src/hooks/dashboard/useDashboardSummary.ts", "options?.snapshot?.daily || model.daily", "model.daily"),
    ("Meta freshness antiga", "src/hooks/dashboard/useDashboardSummary.ts", "options?.snapshot?.sources || model.sources", "model.sources"),
    ("Meta reutiliza leitura anterior", "src/app/DashboardDataContext.tsx", "if (prior) await prior;", "if (false) await prior;"),
]

def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)

def mutations(root, entries, cmd):
    baseline = run(cmd, root)
    if baseline.returncode: raise RuntimeError("Baseline falhou:\n" + baseline.stdout)
    for name, relative, before, after in entries:
        path = root / relative
        original = path.read_text()
        if before not in original: raise RuntimeError("Mutação não aplicada: " + name)
        mutated = original.replace(before, after) if name == "Meta persistência" else original.replace(before, after, 1)
        if "_skip_upsert" in mutated:
            mutated += '\nasync def _skip_upsert(*args, **kwargs):\n    return {"ok": True}\n'
        try:
            path.write_text(mutated)
            result = run(cmd, root)
            detected = result.returncode != 0 and not any(value in result.stdout for value in ["ImportError:", "SyntaxError:", "Transform failed", "Failed to resolve import"])
            print(f"{'DETECTADA' if detected else 'SOBREVIVEU'}: {name}", flush=True)
            if not detected: raise RuntimeError(result.stdout[-4000:])
        finally: path.write_text(original)

def main():
    with tempfile.TemporaryDirectory(prefix="mugo-pipeline-mutations-") as temp:
        root = Path(temp); server = root / "server"
        for folder in ["services", "routes", "tests"]:
            (server / folder).mkdir(parents=True)
            for path in (ROOT / "server" / folder).glob("*.py"):
                shutil.copyfile(path, server / folder / path.name)
        shutil.copyfile(ROOT / "server/api_support.py", server / "api_support.py")
        mutations(server, BACK, [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_manual_refresh_pipeline.py"])
        for path in (ROOT / "src").rglob("*"):
            if path.is_file() and path.suffix in {".ts", ".tsx", ".css", ".json", ".svg"}:
                target = root / path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        for name in ["package.json", "vite.config.ts"]: shutil.copyfile(ROOT / name, root / name)
        (root / "node_modules").symlink_to(ROOT / "node_modules", target_is_directory=True)
        mutations(root, FRONT, [str(ROOT / "node_modules/.bin/vitest"), "run", "src/pages/Ecommerce.test.tsx", "src/components/FbitsIntegrationPanel.test.tsx", "src/pages/Dashboard.channelReport.test.tsx", "src/hooks/dashboard/useDashboardSummary.refresh.test.tsx", "src/app/DashboardDataContext.test.tsx"])
        print(f"Resultado: {len(BACK)+len(FRONT)}/{len(BACK)+len(FRONT)} mutações detectadas")
    return 0
if __name__ == "__main__": raise SystemExit(main())
