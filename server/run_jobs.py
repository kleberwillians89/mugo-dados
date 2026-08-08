from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from services.env_loader import ensure_env_loaded

ensure_env_loaded()

from services.ads_sync import sync_ads_for_client_period
from services.cron_jobs import (
    run_daily_instagram_sync,
    run_hourly_ads_sync,
    run_shopify_reconciliation,
    run_token_refresh_job,
)
from services.ga4_sync import sync_ga4_for_period
from services.meta_tokens import refresh_meta_token_for_connection


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def _run(args: argparse.Namespace) -> Any:
    if args.command == "token-refresh":
        return await run_token_refresh_job()
    if args.command == "organic-sync":
        return await run_daily_instagram_sync(limit=args.limit)
    if args.command == "ads-sync-hourly":
        return await run_hourly_ads_sync(window_days=args.days)
    if args.command == "ads-backfill":
        return await sync_ads_for_client_period(
            client_id=args.client_id,
            connection_id=args.connection_id,
            since=args.since,
            until=args.until,
            job_name="meta_ads_manual_backfill",
            trigger_source="manual_cli",
            record_job_run=True,
        )
    if args.command == "ga4-sync":
        return await sync_ga4_for_period(
            since=args.since,
            until=args.until,
            days=args.days,
            client_id=args.client_id,
            job_name="ga4_sync_cli",
            trigger_source="manual_cli",
            record_job_run=True,
        )
    if args.command == "refresh-token":
        return await refresh_meta_token_for_connection(args.connection_id)
    if args.command == "shopify-reconcile":
        return await run_shopify_reconciliation(fallback_days=args.fallback_days)
    raise RuntimeError(f"Comando não suportado: {args.command}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Executa jobs operacionais de Instagram, Meta Ads e GA4. Pode ser usado localmente ou como base de Cron Jobs no Render."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("token-refresh", help="Renova/valida tokens Meta ativos.")

    organic_sync = sub.add_parser("organic-sync", help="Roda sync recorrente do Instagram orgânico.")
    organic_sync.add_argument("--limit", type=int, default=60, help="Limite de mídias recentes por conexão.")

    ads_sync = sub.add_parser("ads-sync-hourly", help="Roda sync recorrente de Ads na janela recente.")
    ads_sync.add_argument("--days", type=int, default=7, help="Janela recente em dias para resync seguro.")

    backfill = sub.add_parser("ads-backfill", help="Roda sync manual/backfill por cliente e período.")
    backfill.add_argument("--client-id", required=True, help="Client ID dono da conexão.")
    backfill.add_argument("--since", required=True, help="Data inicial no formato YYYY-MM-DD.")
    backfill.add_argument("--until", required=True, help="Data final no formato YYYY-MM-DD.")
    backfill.add_argument("--connection-id", default=None, help="Connection ID opcional para travar a execução.")

    ga4_sync = sub.add_parser("ga4-sync", help="Roda ingestão manual do GA4.")
    ga4_sync.add_argument("--client-id", default=None, help="Client ID obrigatório em produção.")
    ga4_sync.add_argument("--since", default=None, help="Data inicial no formato YYYY-MM-DD.")
    ga4_sync.add_argument("--until", default=None, help="Data final no formato YYYY-MM-DD.")
    ga4_sync.add_argument("--days", type=int, default=30, help="Janela padrão em dias quando since/until não forem informados.")

    refresh = sub.add_parser("refresh-token", help="Força refresh manual de uma conexão específica.")
    refresh.add_argument("--connection-id", required=True, help="Connection ID a ser renovado.")

    shopify_reconcile = sub.add_parser(
        "shopify-reconcile",
        help="Reconciliação periódica leve de todas as lojas Shopify conectadas (webhooks continuam sendo a fonte em tempo real).",
    )
    shopify_reconcile.add_argument(
        "--fallback-days", type=int, default=30,
        help="Janela em dias quando ainda não houve sync anterior registrado.",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _print_json(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
