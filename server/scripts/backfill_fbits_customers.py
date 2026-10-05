"""Executar somente em ambiente backend controlado, com tenant confirmado."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.fbits_customer_backfill import backfill_customer_identities


def parse_args():
    parser = argparse.ArgumentParser(description="Preenche contatos FBITS no intervalo dos pedidos persistidos de UM tenant. Contagens por página, não clientes únicos.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--confirm-client-id", required=True)
    parser.add_argument("--apply", required=True, action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(backfill_customer_identities(client_id=args.client_id, confirm_client_id=args.confirm_client_id))
    except Exception:
        # Nunca imprimir traceback/payload/credenciais de exceções externas.
        print("Backfill interrompido. Consulte as contagens e verifique a conexão/tabela FBITS.", file=sys.stderr)
        sys.exit(1)
