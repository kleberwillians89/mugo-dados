from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.meta_reprocessing import reprocess_meta_purchase_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recalculate Meta purchase metrics from persisted raw_json.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--apply", action="store_true", help="Persist recalculated columns and refresh the read model.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    result = await reprocess_meta_purchase_metrics(
        client_id=args.client_id,
        start=args.start,
        end=args.end,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
