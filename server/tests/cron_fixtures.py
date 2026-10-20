"""Default active-company DB fixture for existing provider cron unit tests."""
import json

async def active_companies(table, *, select, filters, limit):
    assert table == 'clients' and select == 'id,status'
    ids = json.loads('[' + filters['id'][4:-1] + ']')
    assert len(ids) <= limit <= 100
    return [{'id': cid, 'status': 'active'} for cid in ids]
