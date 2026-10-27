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
    for key, value in dotenv_values(stream=io.StringIO(raw)).items():
        if key and value is not None:
            env[key] = value
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
