"""CLI import of a ČSOB CSV statement — headless version of POST /import.

Usage:
    uv run python -m finance.import_cli /path/to/statement.csv

Prints a one-line result to stdout and exits with code 0 on success, 1 on error.
Meant to be called from scripts or automations (drop a CSV → import).
"""

from __future__ import annotations

import sys
from pathlib import Path

from finance import db
from finance.csv_import import parse_csob_csv


def import_csv(path: str | Path) -> str:
    content = Path(path).read_bytes()
    info, txs = parse_csob_csv(content)
    if not txs:
        raise ValueError("No transactions in the file")

    account_no = info["account_no"] or "manual"
    currency = info["currency"]
    iban = f"CSOB-CZ-{account_no}"
    payload = {
        "session_id": "manual-csob-cz",
        "aspsp": {"name": "ČSOB CZ (manual)", "country": "CZ"},
        "access": {"valid_until": None},
        "accounts": [
            {
                "uid": iban,
                "account_id": {"iban": iban},
                "currency": currency,
                "name": f"ČSOB CZ {account_no}",
            }
        ],
    }
    ids = db.save_session_and_accounts(payload)
    inserted, updated = db.upsert_transactions(ids[0], txs)
    fx_fetched, _ = db.backfill_fx_rates()
    fx_note = f", FX rates +{fx_fetched}" if fx_fetched else ""
    return f"✅ ČSOB {account_no}: {inserted} new, {updated} updated{fx_note}"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: python -m finance.import_cli <statement.csv>", file=sys.stderr)
        return 2
    db.init_db()
    try:
        print(import_csv(args[0]))
    except (ValueError, UnicodeDecodeError, FileNotFoundError) as e:
        print(f"❌ Import failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
