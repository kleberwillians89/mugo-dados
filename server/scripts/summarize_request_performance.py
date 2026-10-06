"""Analisa exportação local dos novos logs; nenhuma rede ou credencial."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import median


def summarize(text):
    requests, dependencies = [], []
    for line in text.splitlines():
        for marker, target in (("[performance][request] ", requests), ("[performance][dependency] ", dependencies)):
            if marker not in line:
                continue
            try:
                target.append(json.loads(line.split(marker, 1)[1]))
            except (ValueError, TypeError):
                continue
    grouped = defaultdict(lambda: {"low": [], "high": []})
    for row in dependencies:
        key = (row.get("dependency"), row.get("operation"), row.get("phase"))
        bucket = "low" if row.get("inflight_at_start", 0) <= 2 else "high"
        grouped[key][bucket].append(float(row["duration_ms"]))
    return {
        "waterfall": [{key: row.get(key) for key in ("request_id", "started_at", "endpoint", "tenant_scope", "start", "end", "days", "offset", "limit", "status", "duration_ms", "supabase_round_trips", "phases", "unclassified_ms")}
                      for row in sorted(requests, key=lambda row: row.get("started_at", ""))],
        "latency_by_concurrency": [{"dependency": key[0], "operation": key[1], "phase": key[2],
            **{bucket: {"samples": len(values), "median_ms": median(values) if values else None,
                        "p95_ms": sorted(values)[max(0, int(len(values) * .95 + .999) - 1)] if values else None}
               for bucket, values in groups.items()}}
            for key, groups in grouped.items()],
        "note": "Concorrência é local ao processo; correlação não prova causalidade. Comparar o mesmo endpoint, tenant e janela em navegações separadas.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.log_file.read_text()), ensure_ascii=False, indent=2))
