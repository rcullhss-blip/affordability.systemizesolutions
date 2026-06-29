"""
V2 — Estimated claim value per lender  (SANDBOX / TEST FEATURE)
==============================================================

Credit reports do NOT contain APR, so a real "APR x term" figure cannot be read
from the data. This module produces a deliberately CONSERVATIVE, indicative
estimate of the redress a borrower might recover on an unaffordable-lending
claim: a refund of the interest and charges PAID, plus statutory interest.

Design principles (agreed with the business):
  * Every account maps to a category — including a catch-all for anything we
    have never seen before, so nothing slips through.
  * Rates sit at the LOWER end of what these lenders really charge, so figures
    read as careful and credible rather than inflated.
  * Instalment loans amortise (the balance falls over the term) so their true
    interest is well below principal x APR x term — we apply a factor for that.
  * High-cost short-term / doorstep credit is hard-capped (FCA cost cap: total
    cost can never exceed 100% of the amount borrowed).
  * Non-credit accounts (phone / utility / current account) carry no interest,
    so they are excluded — no value is put on them.

Everything is gated behind CLAIM_VALUE_ESTIMATE_ENABLED so it stays OFF on the
live V1 stack and only switches on for the V2 sandbox.
"""

import os
from datetime import date, datetime


# ── Feature flag ──────────────────────────────────────────────────────────────
def is_enabled() -> bool:
    return os.getenv("CLAIM_VALUE_ESTIMATE_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ── Conservative representative APRs by category (lower end of real market) ────
# Decimal annual rate. Assumptions, NOT read from the credit file. Single source
# of truth — tune here.
ASSUMED_APR = {
    "CREDIT_CARD":   0.349,   # sub-prime cards (Cap One / Aqua / Marbles ~34.9%)
    "STORE_CARD":    0.299,
    "MAIL_ORDER":    0.399,   # catalogue (Very / Littlewoods)
    "CATALOGUE":     0.399,
    "OVERDRAFT":     0.399,
    "PERSONAL_LOAN": 0.249,
    "HIRE_PURCHASE": 0.269,   # car / motor finance (sub-prime ~32%, kept lower)
}
DEFAULT_APR = 0.249  # catch-all: anything unrecognised -> conservative loan rate

# Non-credit account types — no interest to refund, excluded from estimation.
NON_CREDIT_TYPES = {"CURRENT_ACCOUNT", "TELECOM", "UTILITY"}

# Secured lending — a known category, but these affordability/irresponsible-
# lending claims target UNSECURED consumer credit, so we put no claim value on a
# mortgage or secured loan (a 5.5% rate on a £200k mortgage looks inflated and is
# the wrong claim type). Categorised, but excluded from the figure.
SECURED_TYPES = {"MORTGAGE", "SECURED_LOAN"}

# High-cost short-term / doorstep credit. FCA cost cap: total interest + charges
# can never exceed 100% of the amount borrowed. We estimate at HALF the cap as a
# conservative typical figure (a single on-time loan costs far less than the cap).
HIGH_COST_TYPES = {"PAYDAY_LOAN", "HOME_CREDIT"}
HIGH_COST_FRACTION = 0.50      # conservative typical
HIGH_COST_CAP = 1.00           # legal ceiling (never exceed principal)

# Bureau feeds often code high-cost short-term lenders as ordinary loans, so we
# also fingerprint them by name and treat them as high-cost regardless of type.
HCSTC_LENDER_HINTS = {
    "sunny", "quickquid", "wonga", "lending stream", "payday", "myjar", "satsuma",
    "provident", "mr lender", "peachy", "cashfloat", "drafty", "loans2go", "ferratum",
    "pounds to pocket", "money shop", "uncle buck", "quidmarket", "cash converters",
    "everyday loans", "likely loans", "247moneybox", "fund ourselves", "moneyboat",
    "lendingstream", "buddy loans", "quidie", "cash4unow", "the money platform",
}

# Instalment products amortise (balance falls over the term); revolving balances
# persist. These factors convert the simple figure into a realistic, conservative
# estimate of interest actually paid.
AMORTISING_TYPES = {"PERSONAL_LOAN", "HIRE_PURCHASE", "SECURED_LOAN", "MORTGAGE"}
AMORTISE_FACTOR = 0.55     # instalment loans (validated vs Moneybarn example)
REVOLVING_FACTOR = 0.70    # cards / overdraft / catalogue: avg balance < snapshot

# Statutory interest (FOS). For complaints referred from 1 Jan 2026 the rate is
# Bank of England base + 1% (base 3.75% -> 4.75%). Configurable. Applied over
# half the account life because interest is paid gradually, not all up-front.
STATUTORY_RATE = float(os.getenv("CLAIM_VALUE_STATUTORY_RATE", "0.0475"))

MIN_MONTHS = 1
MAX_MONTHS = 120  # cap accrual at 10 years for an estimate


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
    opened = _parse_date(acc.get("opened_date"))
    if not opened:
        return MIN_MONTHS
    end = (
        _parse_date(acc.get("settled_date"))
        or _parse_date(acc.get("closed_date"))
        or _parse_date(acc.get("default_date"))
        or date.today()
    )
    months = (end.year - opened.year) * 12 + (end.month - opened.month)
    return max(MIN_MONTHS, min(MAX_MONTHS, months))


def categorise(acc: dict) -> str:
    """
    Map an account to a pricing category. Every account resolves to one, with an
    'UNKNOWN' catch-all so nothing is ever left out. Lender-name fingerprints
    promote disguised high-cost short-term lenders to HCSTC.
    """
    acc_type = (acc.get("account_type") or "").strip().upper()
    lender = (acc.get("lender") or "").lower()

    if any(h in lender for h in HCSTC_LENDER_HINTS):
        return "HIGH_COST"
    if acc_type in HIGH_COST_TYPES:
        return "HIGH_COST"
    if acc_type in NON_CREDIT_TYPES:
        return "NON_CREDIT"
    if acc_type in SECURED_TYPES:
        return "SECURED"
    if acc_type in ASSUMED_APR:
        return acc_type
    return "UNKNOWN"


def _exposure(acc: dict) -> float:
    """Best available principal proxy: balance, else credit limit (settled/closed
    loans often show a £0 balance even though interest was paid over their life)."""
    for key in ("balance", "credit_limit"):
        try:
            v = float(acc.get(key) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return v
    return 0.0


def estimate_for_account(acc: dict) -> dict | None:
    """Conservative indicative redress for one account, or None if not applicable."""
    if not acc:
        return None

    category = categorise(acc)
    if category in ("NON_CREDIT", "SECURED"):
        return None  # no interest to refund / wrong claim type for secured lending

    exposure = _exposure(acc)
    if exposure <= 0:
        return None  # no figure to base an estimate on

    months = _months_active(acc)
    years = months / 12.0

    if category == "HIGH_COST":
        # Capped product: interest a conservative fraction of principal, never
        # above the FCA 100%-of-principal ceiling.
        interest = min(exposure * HIGH_COST_FRACTION, exposure * HIGH_COST_CAP)
        apr_shown = None
    else:
        apr = ASSUMED_APR.get(category, DEFAULT_APR)
        factor = AMORTISE_FACTOR if category in AMORTISING_TYPES else REVOLVING_FACTOR
        interest = exposure * apr * years * factor
        apr_shown = apr

    # Statutory interest over ~half the life (interest paid gradually).
    statutory = interest * STATUTORY_RATE * (years / 2.0)
    total = interest + statutory

    total_rounded = int(round(total / 50.0) * 50)
    if total_rounded <= 0:
        return None  # negligible — show nothing rather than a misleading "£0"

    return {
        "estimated_redress": total_rounded,
        "interest_component": round(interest),
        "statutory_component": round(statutory),
        "category": category,
        "assumed_apr": apr_shown,
        "months_active": months,
        "basis_balance": round(exposure),
        "account_type": (acc.get("account_type") or "OTHER").strip().upper(),
    }


def estimate_for_lender(lender_name: str, accounts: list) -> dict | None:
    if not lender_name:
        return None
    acc = next(
        (a for a in accounts
         if (a.get("lender", "") or "").lower() == lender_name.lower()),
        None,
    )
    return estimate_for_account(acc) if acc else None


def portfolio_total(in_scope_results, accounts: list) -> int:
    total = 0
    for r in in_scope_results:
        lender = getattr(r, "lender_name", None)
        est = estimate_for_lender(lender, accounts)
        if est:
            total += est["estimated_redress"]
    return total
