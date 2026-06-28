"""
V2 — Estimated claim value per lender  (SANDBOX / TEST FEATURE)
==============================================================

Credit reports do NOT contain APR / interest rate, so a real "APR x term"
figure cannot be read from the data. This module produces an INDICATIVE
estimate of the redress a borrower might recover on an unaffordable-lending
claim, using an assumed representative APR per product type applied to the
balance over the months the account was live.

In an unaffordable-lending claim the redress is normally a refund of the
INTEREST AND CHARGES PAID on the unaffordable borrowing, plus 8% statutory
interest. So we model interest paid, not "rate x term".

⚠️  Every number this produces is an ESTIMATE for triage/illustration only.
    It is not a calculation of entitlement and must be reviewed by a solicitor.

The whole feature is gated behind the CLAIM_VALUE_ESTIMATE_ENABLED env flag so
it stays OFF on the live (V1) stack and only switches on for the V2 sandbox.
The assumed APR table below is deliberately a single, well-commented constant
so the rates can be tuned during testing without hunting through the codebase.
"""

import os
from datetime import date, datetime


# ── Feature flag ──────────────────────────────────────────────────────────────
def is_enabled() -> bool:
    """V2-only. Off unless explicitly enabled on the sandbox stack."""
    return os.getenv("CLAIM_VALUE_ESTIMATE_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ── Assumed representative APRs by product type (TUNABLE) ─────────────────────
# Decimal annual rate. These are assumptions, NOT read from the credit file.
# Tune freely during V2 testing — this is the single source of truth.
ASSUMED_APR = {
    "PAYDAY_LOAN":   2.00,   # high-cost short-term; capped below by FCA cost cap
    "STORE_CARD":    0.35,
    "OVERDRAFT":     0.39,
    "CREDIT_CARD":   0.30,
    "PERSONAL_LOAN": 0.25,
    "HIRE_PURCHASE": 0.18,   # motor finance / HP
    "MORTGAGE":      0.05,
    "OTHER":         0.25,
}
DEFAULT_APR = 0.25

# FCA total-cost cap for high-cost short-term credit: a borrower never repays
# more than 100% of the amount borrowed in interest + charges. So payday-type
# estimated interest is capped at 1.0x the balance.
PAYDAY_COST_CAP_MULTIPLE = 1.0
PAYDAY_TYPES = {"PAYDAY_LOAN"}

# 8% simple statutory interest, applied over the months the account was live.
STATUTORY_RATE = 0.08

# Guardrails so a dodgy date can't produce a silly figure.
MIN_MONTHS = 1
MAX_MONTHS = 120  # cap at 10 years of accrual for an estimate


def _parse_date(val):
    if not val:
        return None
    if isinstance(val, (date, datetime)):
        return val if isinstance(val, date) else val.date()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%B %Y", "%b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(val), fmt).date()
        except ValueError:
            pass
    return None


def _months_active(acc) -> int:
    """Months from opened_date to the close/default date (or today)."""
    opened = _parse_date(acc.get("opened_date"))
    if not opened:
        return 0
    end = (
        _parse_date(acc.get("settled_date"))
        or _parse_date(acc.get("closed_date"))
        or _parse_date(acc.get("default_date"))
        or date.today()
    )
    months = (end.year - opened.year) * 12 + (end.month - opened.month)
    return max(MIN_MONTHS, min(MAX_MONTHS, months))


def estimate_for_account(acc: dict) -> dict | None:
    """
    Indicative redress estimate for one account.

    Returns a dict with the figure and the assumptions used (for the report
    footnote), or None if there isn't enough data to estimate.
    """
    if not acc:
        return None

    acc_type = (acc.get("account_type") or "OTHER").strip().upper()

    # Exposure: balance, falling back to credit limit if balance is missing.
    try:
        balance = float(acc.get("balance") or acc.get("credit_limit") or 0)
    except (TypeError, ValueError):
        balance = 0.0
    if balance <= 0:
        return None

    apr = ASSUMED_APR.get(acc_type, DEFAULT_APR)
    months = _months_active(acc)
    years = months / 12.0

    interest = balance * apr * years

    # FCA cost cap for payday / high-cost short-term credit.
    if acc_type in PAYDAY_TYPES:
        interest = min(interest, balance * PAYDAY_COST_CAP_MULTIPLE)

    statutory = interest * STATUTORY_RATE * years
    total = interest + statutory

    # Round to the nearest £50 — signals "estimate", not a precise figure.
    total_rounded = round(total / 50.0) * 50

    return {
        "estimated_redress": total_rounded,
        "interest_component": round(interest),
        "statutory_component": round(statutory),
        "assumed_apr": apr,
        "months_active": months,
        "basis_balance": round(balance),
        "account_type": acc_type,
    }


def estimate_for_lender(lender_name: str, accounts: list) -> dict | None:
    """Find the account matching a lender result and estimate for it."""
    if not lender_name:
        return None
    acc = next(
        (a for a in accounts
         if (a.get("lender", "") or "").lower() == lender_name.lower()),
        None,
    )
    return estimate_for_account(acc) if acc else None


def portfolio_total(in_scope_results, accounts: list) -> int:
    """Sum of estimated redress across all in-scope lenders. 0 if none."""
    total = 0
    for r in in_scope_results:
        lender = getattr(r, "lender_name", None)
        est = estimate_for_lender(lender, accounts)
        if est:
            total += est["estimated_redress"]
    return total
