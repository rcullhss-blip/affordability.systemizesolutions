"""
Computes a financial snapshot of the client's position on the exact date
a lender approved credit. This snapshot drives the dynamic LOC content.
"""
from datetime import date, datetime, timedelta
from typing import Optional
from app.analysis.lender_classifier import classify_lender


def compute_at_lending(
    lending_date: Optional[date],
    all_accounts: list[dict],
    all_searches: list[dict],
    all_defaults: list[dict],
    target_lender: str,
) -> dict:
    if not lending_date:
        return _empty_snapshot()

    # Accounts that were open on the lending date (opened before, not yet closed)
    active_accounts = [
        a for a in all_accounts
        if _parse_date(a.get("opened_date")) and _parse_date(a.get("opened_date")) < lending_date
        and a.get("lender", "").lower() != target_lender.lower()
    ]

    total_debt = sum(a.get("balance") or 0 for a in active_accounts)
    total_limit = sum(a.get("credit_limit") or 0 for a in active_accounts)
    utilisation = round(total_debt / total_limit * 100, 1) if total_limit > 0 else 0.0

    # Defaults registered before the lending date
    active_defaults = [
        d for d in all_defaults
        if _parse_date(d.get("date")) and _parse_date(d.get("date")) < lending_date
    ]

    # Missed payments in 6 months prior
    six_months_prior = lending_date - timedelta(days=182)
    missed_payments_6m = _count_missed_payments_in_window(active_accounts, six_months_prior, lending_date)

    # Application footprint searches in 90 days prior — only confirmed creditApplication type;
    # old records without search_subtype are included for backward compatibility.
    ninety_days_prior = lending_date - timedelta(days=90)
    _APP_SUBTYPES = {None, "APPLICATION"}
    hard_searches_90d = [
        s for s in all_searches
        if _parse_date(s.get("date"))
        and ninety_days_prior <= _parse_date(s.get("date")) < lending_date
        and s.get("search_type", "").upper() == "HARD"
        and s.get("search_subtype", None) in _APP_SUBTYPES
        and target_lender.lower() not in (s.get("lender") or "").lower()
    ]

    # Payday loans active at lending date
    payday_active = [
        a for a in active_accounts
        if classify_lender(a.get("lender", "")) == "payday"
    ]

    # Chronology — key events before and after lending date
    chronology = _build_chronology(lending_date, all_accounts, all_defaults, all_searches, target_lender)

    # Earliest adverse marker
    all_adverse_dates = [
        _parse_date(d.get("date")) for d in all_defaults if _parse_date(d.get("date"))
    ] + [
        _parse_date(a.get("opened_date")) for a in all_accounts
        if _parse_date(a.get("opened_date")) and a.get("status", "").lower() in ("default", "defaulted")
    ]
    earliest_adverse = min(all_adverse_dates).isoformat() if all_adverse_dates else None

    most_recent_default_before = max(
        (_parse_date(d.get("date")) for d in active_defaults if _parse_date(d.get("date"))),
        default=None,
    )

    return {
        "lending_date": lending_date.isoformat(),
        "total_debt": round(total_debt, 2),
        "active_account_count": len(active_accounts),
        "utilisation_pct": utilisation,
        "active_defaults_count": len(active_defaults),
        "active_defaults_list": [
            {"lender": d.get("lender", ""), "date": d.get("date", ""), "amount": d.get("amount", 0)}
            for d in active_defaults
        ],
        "missed_payments_6m_prior": missed_payments_6m,
        "hard_searches_90d_prior": len(hard_searches_90d),
        "payday_loans_active": len(payday_active),
        "chronology": chronology,
        "earliest_adverse_marker_date": earliest_adverse,
        "most_recent_default_before_lending": most_recent_default_before.isoformat() if most_recent_default_before else None,
    }


def _build_chronology(
    lending_date: date,
    accounts: list[dict],
    defaults: list[dict],
    searches: list[dict],
    target_lender: str,
) -> list[dict]:
    events = []

    for acc in accounts:
        d = _parse_date(acc.get("opened_date"))
        if not d:
            continue
        is_target = acc.get("lender", "").lower() == target_lender.lower()
        events.append({
            "date": d.isoformat(),
            "event": f"{'[THIS LENDER] ' if is_target else ''}{acc.get('lender', '')} account opened"
                     + (f" (£{acc.get('credit_limit') or acc.get('balance') or '?':,} limit)" if (acc.get("credit_limit") or acc.get("balance")) else ""),
            "highlight": is_target,
        })

    for d_rec in defaults:
        d = _parse_date(d_rec.get("date"))
        if not d:
            continue
        events.append({
            "date": d.isoformat(),
            "event": f"Default registered — {d_rec.get('lender', '')} (£{d_rec.get('amount', 0):,})",
            "highlight": False,
        })

    for s in searches:
        d = _parse_date(s.get("date"))
        if not d:
            continue
        if s.get("search_type", "").upper() == "HARD":
            subtype = s.get("search_subtype", "APPLICATION")
            subtype_label = {
                "APPLICATION": "credit application", "QUOTATION": "quotation search",
                "MANAGEMENT": "account management check", "IDENTITY": "identity verification",
                "TRACE": "trace search", "INSURANCE": "insurance search",
            }.get(subtype or "APPLICATION", "search")
            events.append({
                "date": d.isoformat(),
                "event": f"Search by {s.get('lender', 'Unknown')} ({subtype_label})",
                "highlight": False,
            })

    events.sort(key=lambda e: e["date"])
    return events


def _count_missed_payments_in_window(accounts: list[dict], start: date, end: date) -> int:
    count = 0
    for acc in accounts:
        status = (acc.get("status") or "").upper()
        # Skip accounts already in default — their D codes form part of the default record itself,
        # not additional missed payments. Counting them would double-count the adverse event.
        if status in ("DEFAULT", "DEFAULTED"):
            continue
        history = acc.get("payment_history") or []
        # Only count genuine adverse codes; exclude U (unclassified), N (not reported), S (settled)
        missed_markers = {"D", "3", "4", "5", "6"}
        count += sum(1 for p in history if str(p).upper() in missed_markers)
    return count


def _parse_date(val) -> Optional[date]:
    if not val:
        return None
    if isinstance(val, date):
        return val
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%B %Y", "%b %Y"):
        try:
            return datetime.strptime(str(val), fmt).date()
        except ValueError:
            continue
    return None


def _empty_snapshot() -> dict:
    return {
        "lending_date": None,
        "total_debt": 0,
        "active_account_count": 0,
        "utilisation_pct": 0,
        "active_defaults_count": 0,
        "active_defaults_list": [],
        "missed_payments_6m_prior": 0,
        "hard_searches_90d_prior": 0,
        "payday_loans_active": 0,
        "chronology": [],
        "earliest_adverse_marker_date": None,
        "most_recent_default_before_lending": None,
    }
