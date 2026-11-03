"""Roda um comando de `server/run_jobs.py` no GitHub Actions sem vazar nada no log.

O repositório é público e os logs do Actions também: por isso a saída do job
(ids, contagens, mensagens de erro de provedores) vai para /dev/null e só uma
linha neutra é impressa (comando, código de saída, duração). O detalhe de cada
execução continua registrado no banco (`cron_job_runs`), visível no painel.

As variáveis vêm de UM segredo do repositório, `MUGO_JOBS_ENV`, no formato
.env (as mesmas chaves do serviço no Render). Nunca são impressas.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

SERVER_DIR = Path(__file__).resolve().parents[2] / "server"


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("uso: run_job.py <comando> [opções]")
        return 2
    raw = os.environ.pop("MUGO_JOBS_ENV", "")
    if not raw.strip():
        print(f"job={args[0]} status=sem_configuracao (segredo MUGO_JOBS_ENV ausente)")
        return 1
    env = {k: v for k, v in os.environ.items()}
    parsed = {k: v for k, v in dotenv_values(stream=io.StringIO(raw)).items() if k and v is not None}
    env.update(parsed)
    # Diagnóstico sem vazar nada: só NOMES de variáveis que faltam ou estão com formato errado.
    problems = []
    if not str(parsed.get("SUPABASE_URL", "")).strip().startswith("https://"):
        problems.append("SUPABASE_URL (precisa começar com https://)")
    if len(str(parsed.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()) < 20:
        problems.append("SUPABASE_SERVICE_ROLE_KEY (vazia ou curta demais)")
    masked = [k for k, v in parsed.items() if set(str(v).strip()) <= {"*", "•", "."} and str(v).strip()]
    if masked:
        problems.append("valores mascarados (copiados com ••• do painel): " + ", ".join(sorted(masked)[:10]))
    if problems:
        print(f"job={args[0]} status=configuracao_invalida variaveis_lidas={len(parsed)} problemas=[{'; '.join(problems)}]")
        print("Use o formato NOME=valor, uma variável por linha, com os valores reais (no Render: Environment → olho/Reveal).")
        return 1
    env.setdefault("APP_ENV", "production")
    env["PYTHONUNBUFFERED"] = "1"
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "run_jobs.py", *args],
        cwd=SERVER_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    seconds = round(time.monotonic() - started)
    status = "ok" if completed.returncode == 0 else "falhou"
    print(f"job={args[0]} status={status} exit={completed.returncode} duracao_s={seconds}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
