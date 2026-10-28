"""Roda um comando de `server/run_jobs.py` no GitHub Actions sem vazar nada no log.

O repositório é público e os logs do Actions também: por isso a saída do job
(ids, mensagens de erro de provedores) nunca é impressa. Só passam linhas
neutras: a final (comando, código de saída, duração) e, no `tick`, uma por job
no formato fechado de SAFE_LINE (nome do job, status, duração e contagem de
falhas). O detalhe de cada execução continua no banco (`cron_job_runs`).

As variáveis vêm de UM segredo do repositório, `MUGO_JOBS_ENV`, no formato
.env (as mesmas chaves do serviço no Render). Nunca são impressas.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

SERVER_DIR = Path(__file__).resolve().parents[2] / "server"
# Única forma de linha do job que chega ao log público (ver services/job_dispatcher.py).
SAFE_LINE = re.compile(
    r"\[tick\] job=[a-z0-9-]{1,40} status=(ok|parcial|falhou|tempo_esgotado|adiado) duracao_s=\d{1,6}( falhas=\d{1,4}/\d{1,4})?"
)


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
        cwd=SERVER_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        text=True, errors="replace",
    )
    for line in completed.stdout.splitlines():
        if SAFE_LINE.fullmatch(line.strip()):
            print(line.strip())
    seconds = round(time.monotonic() - started)
    status = "ok" if completed.returncode == 0 else "falhou"
    print(f"job={args[0]} status={status} exit={completed.returncode} duracao_s={seconds}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
