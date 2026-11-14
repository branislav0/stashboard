"""Generate a standalone demo database with mock data for screenshots.

Uses no real data and never touches a real finance.db — it only writes to the path
in DATABASE_PATH (default: demo.db) and refuses to overwrite finance.db.

Usage:
    DATABASE_PATH=demo.db uv run python scripts/seed_demo.py

Then run the app against the demo DB:
    DATABASE_PATH=demo.db uv run python -m finance.main
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import date
from pathlib import Path

# Demo DB path — set BEFORE importing finance.db (it reads the env at runtime).
DB_PATH = os.environ.setdefault("DATABASE_PATH", "demo.db")
if Path(DB_PATH).name == "finance.db":
    sys.exit("REFUSED: DATABASE_PATH points to finance.db. The demo must not overwrite real data.")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from finance import db  # noqa: E402

random.seed(42)
TODAY = date(2026, 6, 14)


def _raw(counterparty: str, info: str, amount: str, currency: str, cd: str) -> str:
    return json.dumps(
        {
            "transaction_amount": {"amount": amount, "currency": currency},
            "credit_debit_indicator": cd,
            "remittance_information": [info] if info else [],
            ("creditor" if cd == "DBIT" else "debtor"): {"name": counterparty},
        },
        ensure_ascii=False,
    )


def main() -> None:
    db.init_db()  # builds schema + migrations (and seeds default categories)

    with db.connect() as conn:
        # wipe everything – we only want a few categories and mock data
        for tbl in (
            "category_rules",
            "transactions",
            "accounts",
            "sessions",
            "categories",
            "fx_rates",
        ):
            conn.execute(f"DELETE FROM {tbl}")

        # --- session (FK for accounts) ---
        conn.execute(
            "INSERT INTO sessions (session_id, aspsp_name, aspsp_country) VALUES (?, ?, ?)",
            ("demo-session", "Demo Bank", "CZ"),
        )

        # --- accounts: CZK (main) + EUR (multi-currency showcase) ---
        acc = {}
        for key, iban, ccy, name in [
            ("czk", "CZ0000000000000000000001", "CZK", "Current account"),
            ("eur", "LT000000000000000002", "EUR", "Revolut"),
        ]:
            cur = conn.execute(
                "INSERT INTO accounts (iban, currency, bic_fi, name, eb_uid, session_id, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (iban, ccy, "DEMOXXXX", name, f"demo-{key}", "demo-session", "{}"),
            )
            acc[key] = cur.lastrowid

        # --- a few categories ---
        cats = {}
        cat_def = [
            ("Salary", "income"),
            ("Groceries", "expense"),
            ("Restaurants", "expense"),
            ("Transport", "expense"),
            ("Housing", "expense"),
            ("Entertainment", "expense"),
            ("Subscriptions", "expense"),
            ("Savings", "expense"),  # tracked by the savings goal
            ("Internal transfers / FX", "transfer"),
        ]
        for name, kind in cat_def:
            cur = conn.execute(
                "INSERT INTO categories (name, parent_id, kind) VALUES (?, NULL, ?)",
                (name, kind),
            )
            cats[name] = cur.lastrowid

        # monthly budgets
        for name, budget in [
            ("Groceries", 13000),
            ("Restaurants", 5000),
            ("Transport", 7000),
            ("Entertainment", 4000),
        ]:
            conn.execute(
                "UPDATE categories SET monthly_budget_czk = ? WHERE id = ?", (budget, cats[name])
            )

        # a few rules (so the rules page is not empty)
        for cat, pattern in [
            ("Subscriptions", "netflix|spotify|youtube"),
            ("Groceries", "lidl|albert|billa|tesco|kaufland"),
            ("Transport", "shell|omv|mhd|dpp"),
        ]:
            conn.execute(
                "INSERT INTO category_rules (category_id, pattern, field, priority) "
                "VALUES (?, ?, 'any', 50)",
                (cats[cat], pattern),
            )

        # --- transactions ---
        seq = 0

        def tx(account, d, amount, ccy, cd, counterparty, info, cat, tx_type):
            nonlocal seq
            seq += 1
            conn.execute(
                """INSERT INTO transactions
                   (account_id, entry_reference, booking_date, amount, currency,
                    credit_debit, counterparty_name, remittance_info, status,
                    raw_json, category_id, manual_override, tx_type, note, hidden)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'BOOK', ?, ?, 0, ?, NULL, 0)""",
                (
                    account,
                    f"demo-{seq:04d}",
                    d.isoformat(),
                    f"{amount:.2f}",
                    ccy,
                    cd,
                    counterparty,
                    info,
                    _raw(counterparty, info, f"{amount:.2f}", ccy, cd),
                    cats[cat],
                    tx_type,
                ),
            )

        groceries = ["Lidl", "Albert", "Billa", "Tesco", "Kaufland", "Penny Market"]
        restaurants = ["Pizzeria Roma", "Sushi Bar", "Bistro Praha", "KFC", "Kebab House"]
        fuel = ["Shell", "OMV", "Benzina"]
        fun = ["Cinema City", "Steam", "Kino Lucerna", "Booking.com"]

        czk, eur = acc["czk"], acc["eur"]
        last_czk = last_eur = None

        # 6 months: January → June 2026
        for m in range(1, 7):
            day_cap = TODAY.day - 2 if m == TODAY.month else 27

            def rday(lo, hi):
                return date(2026, m, min(random.randint(lo, hi), day_cap))

            # income: salary
            tx(
                czk,
                date(2026, m, min(2, day_cap)),
                random.uniform(100000, 108000),
                "CZK",
                "CRDT",
                "Employer Ltd.",
                "Salary payment",
                "Salary",
                "Incoming transfer",
            )
            # housing (standing order)
            tx(
                czk,
                date(2026, m, min(5, day_cap)),
                24000,
                "CZK",
                "DBIT",
                "Apartment rental",
                "Rent",
                "Housing",
                "Standing order",
            )
            # savings (buffer) — ~66k/month → ~400k over 6 months → 40 % of a 1,000,000 goal
            tx(
                czk,
                date(2026, m, min(3, day_cap)),
                random.uniform(62000, 70000),
                "CZK",
                "DBIT",
                "Savings account",
                "Monthly savings",
                "Savings",
                "Standing order",
            )
            # subscriptions
            for svc, amt in [("Netflix", 239), ("Spotify", 169), ("YouTube Premium", 179)]:
                tx(
                    czk,
                    rday(8, 20),
                    amt,
                    "CZK",
                    "DBIT",
                    svc,
                    "Subscription",
                    "Subscriptions",
                    "Card payment",
                )
            # groceries
            for _ in range(random.randint(6, 9)):
                tx(
                    czk,
                    rday(1, 27),
                    random.uniform(350, 2600),
                    "CZK",
                    "DBIT",
                    random.choice(groceries),
                    "Purchase",
                    "Groceries",
                    "Card payment",
                )
            # restaurants
            for _ in range(random.randint(3, 5)):
                tx(
                    czk,
                    rday(1, 27),
                    random.uniform(400, 1400),
                    "CZK",
                    "DBIT",
                    random.choice(restaurants),
                    "",
                    "Restaurants",
                    "Card payment",
                )
            # transport
            tx(
                czk,
                rday(1, 5),
                750,
                "CZK",
                "DBIT",
                "DPP MHD",
                "Monthly pass",
                "Transport",
                "Card payment",
            )
            for _ in range(random.randint(1, 2)):
                tx(
                    czk,
                    rday(1, 27),
                    random.uniform(1500, 2800),
                    "CZK",
                    "DBIT",
                    random.choice(fuel),
                    "Fuel",
                    "Transport",
                    "Card payment",
                )
            # entertainment
            for _ in range(random.randint(1, 3)):
                tx(
                    czk,
                    rday(1, 27),
                    random.uniform(600, 2200),
                    "CZK",
                    "DBIT",
                    random.choice(fun),
                    "",
                    "Entertainment",
                    "Card payment",
                )

            # EUR account – a few online purchases
            for _ in range(random.randint(2, 4)):
                cat = random.choice(["Entertainment", "Restaurants", "Groceries"])
                merch = {
                    "Entertainment": "Steam",
                    "Restaurants": "Uber Eats",
                    "Groceries": "Amazon",
                }[cat]
                tx(
                    eur,
                    rday(1, 27),
                    random.uniform(10, 90),
                    "EUR",
                    "DBIT",
                    merch,
                    "Online",
                    cat,
                    "Card payment",
                )

        # balances? the app derives them from transactions, not needed.
        last_czk, last_eur  # noqa

    # report
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    print(f"Demo DB ready: {DB_PATH}")
    print(f"  accounts: 2 (CZK + EUR), categories: {len(cat_def)}, transactions: {n}")
    print()
    print("Run the app against the demo DB:")
    print(f"  DATABASE_PATH={DB_PATH} uv run python -m finance.main")


if __name__ == "__main__":
    main()
