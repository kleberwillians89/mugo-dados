"""Mutação dirigida das regras de refresh; cópias temporárias, sem editar o repo.

Executar: python server/tests/run_provider_refresh_mutations.py
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SERVER = Path(__file__).resolve().parents[1]
MUTANTS = [
    ("membership", "routes/integrations.py", "cid = await require_client_read(client_id, authorization)", "cid = client_id"),
    ("campos extras", "routes/integrations.py", 'ConfigDict(extra="forbid")', 'ConfigDict(extra="ignore")'),
    ("allowlist", "services/provider_refresh.py", '"meta", "google"]', '"meta", "google", "openai"]'),
    ("lock concorrente", "services/provider_refresh.py", 'async with guarded_sync(client_id=client_id, provider="data_refresh", connection_id=provider):', 'async with __import__("contextlib").nullcontext():'),
    ("cooldown", "services/provider_refresh.py", 'if not await acquire_sync_lock(client_id, f"refresh_cooldown:{provider}", 60):', 'if False:'),
    ("FBITS cooldown", "services/fbits_connections.py", '    require_fbits_not_in_cooldown(row, now)\n', ''),
    ("token Meta global", "services/meta_tokens.py", 'env_token = "" if persisted_only else _env_access_token()', 'env_token = _env_access_token()'),
    ("identidade Instagram", "services/instagram_sync.py", 'if not ig_user_id and persisted_only:', 'if False:'),
    ("contrato real GA4", "services/ga4_sync.py", "    connection_id: Optional[str] = None,\n", ""),
    ("lock canônico Ads", "services/google_ads.py", "    if not connection_id:\n        context = await resolve_google_ads_context(client_id)\n        connection_id = context.connection_id\n", ""),
    ("payload privado", "services/provider_refresh.py", 'return {"ok": True, "client_id": client_id, "provider": provider}', 'return {"ok": True, "client_id": client_id, "provider": provider, "access_token": "secret"}'),
]


def run(directory: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_provider_refresh.py"], cwd=directory, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mugo-refresh-mutations-") as temp:
        root = Path(temp)
        # Somente fontes Python; nunca copiar .env, configurações ou secrets.
        for relative in ["services", "routes"]:
            target = root / relative
            target.mkdir()
            for source in (SERVER / relative).glob("*.py"):
                shutil.copyfile(source, target / source.name)
        shutil.copyfile(SERVER / "api_support.py", root / "api_support.py")
        (root / "tests").mkdir()
        shutil.copyfile(SERVER / "tests/test_provider_refresh.py", root / "tests/test_provider_refresh.py")
        baseline = run(root)
        if baseline.returncode:
            print("BASELINE FALHOU\n" + baseline.stdout)
            return 1
        killed = 0
        for name, relative, before, after in MUTANTS:
            path = root / relative
            original = path.read_text()
            if before not in original:
                print(f"MUTAÇÃO NÃO APLICADA: {name}")
                return 1
            try:
                path.write_text(original.replace(before, after, 1))
                result = run(root)
                # ImportError não é evidência de teste matando mutação.
                detected = result.returncode != 0 and "ImportError:" not in result.stdout and "SyntaxError:" not in result.stdout
                killed += int(detected)
                print(f"{'DETECTADA' if detected else 'SOBREVIVEU'}: {name}")
                if not detected:
                    print(result.stdout[-2000:])
            finally:
                path.write_text(original)
        print(f"Resultado: {killed}/{len(MUTANTS)} mutações detectadas")
        return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
