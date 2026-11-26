"""
Relatório SOMENTE LEITURA: clientes com acesso total e o que sairia se fossem para "Cliente — Aprovação Final".

Para combinar com a equipe antes de mudar qualquer perfil (nada muda sozinho):
  - lista, por empresa, os membros que NÃO são da equipe Mugô e têm acesso total (ou papel de admin do cliente);
  - mostra os módulos que eles veem hoje e os que perderiam no perfil cliente_aprovacao
    (que deixa só: ver a Aprovação Final, aprovar, pedir ajuste e comentar).

Nunca escreve no banco e não imprime e-mail, telefone ou token: só empresa, id do usuário e módulos.

Uso (com SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no server/.env):
  cd server && python scripts/approval_profile_report.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.env_loader import ensure_env_loaded  # noqa: E402

ensure_env_loaded()

from services import team_access as ta  # noqa: E402
from services.ig_supabase import sb_select  # noqa: E402

TEAM_ROLES = {"agency_admin", "platform_admin", "account_manager"}


def modules(codes) -> list[str]:
    return sorted({ta.MODULE_LABEL.get(c.split(".", 1)[0], c.split(".", 1)[0]) for c in codes if c.endswith(".view")})


async def main() -> None:
    clients = {str(r["id"]): r.get("trade_name") or r.get("name") or r["id"]
               for r in await sb_select("clients", select="id,name,trade_name", limit=1000)}
    rows = await sb_select("client_memberships", select="client_id,user_id,role,status,access_total,permission_preset", limit=5000)
    target = ta.base_codes("cliente_aprovacao")
    found = 0
    for row in sorted(rows, key=lambda r: (clients.get(str(r.get("client_id")), ""), str(r.get("user_id")))):
        role = str(row.get("role") or "").lower()
        if role in TEAM_ROLES or str(row.get("status") or "active") != "active":
            continue
        if not (row.get("access_total") or role in ta.LEGACY_ADMIN_ROLES):
            continue
        access = await ta.member_access(str(row["client_id"]), str(row["user_id"]))
        if not access:
            continue
        found += 1
        lost = modules(set(access["codes"]) - target)
        print(f"- {clients.get(str(row['client_id']), row['client_id'])} · usuário {row['user_id']} "
              f"· perfil atual: {ta.PRESETS.get(str(access.get('preset')), {}).get('label', access.get('preset'))}")
        print(f"    vê hoje: {', '.join(modules(access['codes'])) or 'nada'}")
        print(f"    no perfil Cliente — Aprovação Final deixaria de ver: {', '.join(lost) or 'nada'}")
    print(f"\n{found} membro(s) com acesso total fora da equipe Mugô. Nenhum perfil foi alterado.")


if __name__ == "__main__":
    asyncio.run(main())
