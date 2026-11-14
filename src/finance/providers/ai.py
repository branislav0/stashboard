from __future__ import annotations

import os
from collections.abc import Iterable

import anthropic

DEFAULT_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")
CONFIDENCE_THRESHOLD = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.7"))

# Optional personal hints for the categorization prompt. Kept out of source so the
# repo stays free of personal data; set them in .env if you want the model to
# recognize your own name (self-transfers) and your salary payer as income.
OWNER_NAME = os.getenv("OWNER_NAME", "").strip()
SALARY_PAYER = os.getenv("SALARY_PAYER", "").strip()


class CategorizationError(Exception):
    pass


def _client() -> anthropic.Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise CategorizationError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=key)


_TOOL = {
    "name": "assign_category",
    "description": (
        "Assign a category to a single transaction. Call it once per transaction. "
        "If you are unsure which category fits, do not call it — skip the transaction."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entry_reference": {"type": "string", "description": "Transaction identifier"},
            "category_id": {"type": "integer", "description": "Category ID from the list"},
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confidence 0-1 (0.9+ for clear cases, 0.7 for likely ones)",
            },
        },
        "required": ["entry_reference", "category_id", "confidence"],
    },
}


def _categories_block(categories: Iterable[dict]) -> str:
    lines = []
    for c in categories:
        parent = f" (subcategory of: {c['parent_name']})" if c.get("parent_name") else ""
        lines.append(f"- id {c['id']}: {c['name']} [{c['kind']}]{parent}")
    return "\n".join(lines)


def _examples_block(examples: Iterable[dict]) -> str:
    if not examples:
        return (
            "(no historical examples — the user has not categorized any transaction manually yet)"
        )
    lines = []
    for ex in examples:
        cp = ex.get("counterparty_name") or "—"
        info = (ex.get("remittance_info") or "")[:80]
        lines.append(
            f'- counterparty: "{cp}" | info: "{info}" → category id {ex["category_id"]} ({ex["category_name"]})'
        )
    return "\n".join(lines)


def _txs_block(txs: Iterable[dict]) -> str:
    lines = []
    for t in txs:
        cp = t.get("counterparty_name") or "—"
        info = (t.get("remittance_info") or "")[:120]
        amt = t.get("amount", "?")
        cur = t.get("currency", "")
        cd = "+" if t.get("credit_debit") == "CRDT" else "−"
        lines.append(
            f'- ref: {t["entry_reference"]} | counterparty: "{cp}" | info: "{info}" '
            f"| {cd}{amt} {cur}"
        )
    return "\n".join(lines)


def categorize_transactions(
    txs: list[dict],
    categories: list[dict],
    examples: list[dict] | None = None,
    model: str = DEFAULT_MODEL,
) -> list[dict]:
    """Calls the AI model to categorize a batch of transactions.

    Args:
        txs: rows from db.list_transactions (must contain entry_reference, counterparty_name,
            remittance_info, amount, currency, credit_debit)
        categories: dicts with id, name, kind, parent_name (optional)
        examples: optional historical manually-categorized transactions for few-shot

    Returns:
        list of {"entry_reference": str, "category_id": int, "confidence": float}
        — only items with confidence >= CONFIDENCE_THRESHOLD are returned.
    """
    if not txs:
        return []
    if not categories:
        raise CategorizationError("No categories defined yet")

    # Personal hints injected only when configured via env (see OWNER_NAME / SALARY_PAYER).
    income_hint = ""
    if SALARY_PAYER:
        income_hint += f"{SALARY_PAYER}, "
    if OWNER_NAME:
        income_hint += f"{OWNER_NAME} (own transfer), "
    owner_clause = f", or it is '{OWNER_NAME}'" if OWNER_NAME else ""

    system = (
        "You categorize personal bank transactions from SK/CZ/EU banks. "
        "Your task: assign a category ID from the list to each transaction by calling the "
        "`assign_category` tool.\n\n"
        "Look for the merchant name in `counterparty_name` or in `info` (remittance) — it is "
        "often there even when the counterparty is a generic 'Transakce platební kartou'.\n\n"
        "## Common merchants (SK/CZ)\n\n"
        "**Groceries / supermarkets:**\n"
        "Tesco, Lidl, Kaufland, Albert, Billa, COOP, Jednota, Hruška, Globus, Penny, "
        "Norma, Žabka, ALBERT VAM DEKUJE, Můj obchod, Pramen, Potraviny.\n\n"
        "**Restaurants / fast food / cafes:**\n"
        "McDonald's, KFC, Burger King, Subway, Bageterie Boulevard, Costa Coffee, Starbucks, "
        "Nordsee, Pizza Hut, Ugo, Damejidlo, Wolt, Bolt Food, Foodora, Restaurace, Bistro, Cafe.\n\n"
        "**Transport:**\n"
        "Bolt, Uber, Liftago, MHD, DPP, IDS, ČD (České dráhy), ZSSK, Leo Express, RegioJet, "
        "FlixBus, Shell, OMV, MOL, Slovnaft, Benzina, "
        "DHL, GLS, Zásilkovna, ULOŽENKA, Packeta.\n\n"
        "**Housing / utilities:**\n"
        "ČEZ, E.ON, PRE, innogy, ZSE, SPP, Slovak Telekom, O2, Orange, T-Mobile, Vodafone, "
        "UPC, Magenta, mortgage (hypotéka), internet, rent (nájom), energy (energie).\n\n"
        "**Subscriptions / online services:**\n"
        "Netflix, Spotify, HBO, Apple, Google, Microsoft, Amazon, AWS, GitHub, Cloudflare, "
        "Adobe, Notion, Slack, Zoom, Strava, "
        "Steam, PlayStation, Xbox, YouTube Premium, Disney+, Audible.\n\n"
        "**E-shops / clothing / household:**\n"
        "Alza, Mall.cz, Heureka, Notino, Datart, IKEA, Kik, Pepco, H&M, Zara, "
        "C&A, NewYorker, Dr. Max, Benu, lekáreň, drogerie, Rossmann, dm, Teta, Hornbach, "
        "Bauhaus, OBI, JYSK, XXXLutz, Albo, Sportisimo, Decathlon.\n\n"
        "**Bank / fees / transfers:**\n"
        "Poplatok, Bank fee, ATM výber, Cash withdrawal, Trvalý príkaz, Inkaso, "
        "úrok, kontokorent.\n\n"
        "**Income (CRDT):**\n"
        f"Mzda, výplata, plat, Salary, {income_hint}"
        "refund (vrátená platba), cashback, dividend, interest credited.\n\n"
        "## Rules\n"
        "- Use substring matching against the merchant names above (e.g. 'ALBERT VAM DEKUJE' → "
        "  Albert → groceries). Case does not matter.\n"
        "- A clear merchant from the list → confidence 0.85-0.95.\n"
        "- A purely generic description ('Transakce platební kartou' and nothing else) → "
        "  skip it, do not categorize.\n"
        "- Negative amounts are expenses (DBIT), positive amounts are income (CRDT). "
        "  Map to a category of the matching `kind`.\n"
        "- For transfers between the owner's own accounts "
        f"(the counterparty has the same surname as the owner{owner_clause}) "
        "use a category of kind 'transfer'.\n"
        "- **The user's historical examples take priority** over your general knowledge. "
        "  If the user categorized a similar transaction differently, do the same.\n"
        "- Confidence: 0.9+ for clear cases, 0.7-0.9 for a reasonable guess, below 0.7 SKIP.\n"
    )

    user = (
        f"## Categories\n{_categories_block(categories)}\n\n"
        f"## Historical examples (what the user categorized manually in the past)\n"
        f"{_examples_block(examples or [])}\n\n"
        f"## Transactions to categorize\n{_txs_block(txs)}\n\n"
        "Call `assign_category` for each transaction (or skip it if you are unsure)."
    )

    client = _client()
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {"type": "text", "text": system},
        ],
        tools=[_TOOL],
        messages=[{"role": "user", "content": user}],
    )

    results: list[dict] = []
    for block in resp.content:
        if block.type == "tool_use" and block.name == "assign_category":
            inp = block.input
            try:
                conf = float(inp.get("confidence", 0))
                if conf < CONFIDENCE_THRESHOLD:
                    continue
                results.append(
                    {
                        "entry_reference": str(inp["entry_reference"]),
                        "category_id": int(inp["category_id"]),
                        "confidence": conf,
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    return results
