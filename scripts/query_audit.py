from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_LOG_PATH = Path(os.getenv("AUDIT_LOG_PATH", "data/audit.jsonl"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Query and inspect audit logs")
    parser.add_argument("--actor", help="Filter by actor (e.g. admin, engineer, system)")
    parser.add_argument("--action", help="Filter by action (e.g. INCIDENT_ENABLE, PROMPT_ROLLBACK)")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of records to show")
    args = parser.parse_args()

    if not AUDIT_LOG_PATH.exists():
        print(f"Chua co file audit log tai {AUDIT_LOG_PATH}.")
        return

    records: list[dict] = []
    with AUDIT_LOG_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    filtered = [
        r for r in records
        if (not args.actor or r.get("actor") == args.actor)
        and (not args.action or r.get("action") == args.action)
    ]

    print(f"=== AUDIT LOGS ({len(filtered)} / {len(records)} events) ===")
    header = f"{'audit_id':<16} {'ts':<24} {'actor':<10} {'action':<18} {'resource':<24} {'status':<8}"
    print(header)
    print("-" * len(header))

    for r in filtered[-args.limit:]:
        print(
            f"{r.get('audit_id', ''):<16} "
            f"{r.get('ts', '')[:23]:<24} "
            f"{r.get('actor', ''):<10} "
            f"{r.get('action', ''):<18} "
            f"{r.get('resource', ''):<24} "
            f"{r.get('status', ''):<8}"
        )


if __name__ == "__main__":
    main()
