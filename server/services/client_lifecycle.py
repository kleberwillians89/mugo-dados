"""Persisted company lifecycle, without deleting history or changing permissions."""
from __future__ import annotations
import json
from .ig_supabase import sb_select


def is_operational(row):
    # Missing status is accepted only for legacy presentation rows, never cron IO.
    return str((row or {}).get('status') or 'active').lower() not in {'inactive', 'archived'}


async def operational_connections(connections):
    """Bounded lookups per invocation. Fail closed if the company read fails."""
    ids = sorted({str(row.get('client_id') or '') for row in connections if row.get('client_id')})
    active = set()
    for offset in range(0, len(ids), 100):
        batch = ids[offset:offset+100]
        rows = await sb_select('clients', select='id,status',
            filters={'id': 'in.(' + ','.join(json.dumps(cid) for cid in batch) + ')'}, limit=len(batch))
        active.update(str(row['id']) for row in rows if str(row.get('id')) in batch and row.get('status') == 'active')
    return [row for row in connections if str(row.get('client_id') or '') in active]
