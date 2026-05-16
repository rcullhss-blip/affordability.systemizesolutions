"""
Deterministic affordability rules engine.
All traffic light decisions are evidence-based. AI is not used here.
"""
from datetime import date, datetime
from typing import Any

GREEN_THRESHOLD = 60
AMBER_THRESHOLD = 25

_TODAY = date.today()

# Confirmed application search subtypes. Records without a subtype (pre-classification)
# are also counted to maintain backward compatibility with older parsed data.
_APPLICATION_SUBTYPES = {None, "APPLICATION"}

# Evidence confidence weights — higher = stronger legal indicator
_CONFIDENCE_WEIGHTS = {
    "ACTIVE_ADVERSE_AT_LENDING":  5,
    "DEFAULT_REGISTERED":         4,
    "REPEATED_MISSED_PAYMENTS":   4,
    "PAYDAY_LOAN":                4,
    "ACTIVE_CCJ":                 4,
    "MULTIPLE_CCJS":              5,
    "PUBLIC_RECORD_INSOLVENCY":   3,
    "HIGH_UTILISATION":           3,
    "MULTIPLE_HARD_SEARCHES":     3,
    "REPEAT_BORROWING":           3,
    "DEBT_STACKING":              2,
    "HARD_SEARCHES":              2,
    "ELEVATED_UTILISATION":       2,
    "MISSED_PAYMENT":             1,
    "POSSIBLE_DEBT_PURCHASER":    0,  # Informational — does not strengthen claim
}
_CONFIDENCE_MAX = 14  # max realistic weight for a single lender (e.g. 2×CRITICAL + 3×HIGH)


def _within_limitation(acc: dict) -> bool:
    """
    Returns True if this account is within the 6-year limitation period.
    Still-active accounts (no settled/default date) are always within limitation
    per Smith v RBS [2023] UKSC 34.
    """
    settled = _parse_date(acc.get("settled_date"))
    default = _parse_date(acc.get("default_date"))
    end_date = settled or default
    if not end_date:
        return True
    years_since = (_TODAY - end_date).days / 365.25
    return years_since <= 6


def analyse_lender(
    lender_name: str,
    accounts: list[dict],
    searches: list[dict],
    defaults: list[dict],
    full_schema: dict,
) -> dict[str, Any]:
    flags = []
    score = 0

    # Filter to accounts within limitation period
    viable_accounts = [a for a in accounts if _within_limitation(a)]
    if not viable_accounts:
        return {
            "traffic_light": "RED",
            "score": 0,
            "flags": [{"type": "OUTSIDE_LIMITATION", "severity": "LOW",
                       "description": f"All accounts with {lender_name} are outside the 6-year limitation period."}],
            "evidence": f"Accounts with {lender_name} fall outside the 6-year limitation period for affordability claims.",
            "confidence": {"score": 0, "grade": "Low"},
        }

    # Per-lender deduplication flags
    _adverse_fired  = False
    _searches_fired = False
    _util_fired     = False

    for acc in viable_accounts:
        opened       = _parse_date(acc.get("opened_date"))
        account_type = (acc.get("account_type") or "").upper()

        # --- Payday loan presence ---
        if account_type == "PAYDAY_LOAN":
            score += 30
            flags.append({"type": "PAYDAY_LOAN", "severity": "HIGH",
                          "description": f"Payday / high-cost short-term loan identified with {lender_name}"})

        # --- High credit utilisation (fire once per lender) ---
        if not _util_fired:
            util = acc.get("utilisation_pct")
            if util is not None:
                if util >= 90:
                    score += 20
                    _util_fired = True
                    if util > 500:
                        util_desc = (
                            f"{lender_name}: outstanding balance materially exceeded the available "
                            f"credit facility — evidence of sustained reliance on credit"
                        )
                    else:
                        util_desc = (
                            f"{lender_name}: credit utilisation at {util:.0f}% — "
                            f"high reliance on available credit facility"
                        )
                    flags.append({"type": "HIGH_UTILISATION", "severity": "HIGH",
                                  "description": util_desc})
                elif util >= 75:
                    score += 10
                    _util_fired = True
                    flags.append({"type": "ELEVATED_UTILISATION", "severity": "MEDIUM",
                                  "description": f"{lender_name}: elevated credit utilisation at {util:.0f}%"})

        # --- Missed payments / adverse payment markers ---
        payment_history = acc.get("payment_history") or []
        status = (acc.get("status") or "").upper()
        # Only count on non-defaulted accounts; exclude U/N/S codes
        if status not in ("DEFAULT", "DEFAULTED"):
            missed = sum(1 for p in payment_history if str(p).upper() in {"D", "3", "4", "5", "6"})
            if missed >= 3:
                score += 25
                flags.append({"type": "REPEATED_MISSED_PAYMENTS", "severity": "HIGH",
                              "description": (
                                  f"Persistent adverse repayment conduct on {lender_name} account — "
                                  f"multiple payment arrears markers on file at time of lending"
                              )})
            elif missed >= 1:
                score += 10
                flags.append({"type": "MISSED_PAYMENT", "severity": "MEDIUM",
                              "description": (
                                  f"Adverse payment markers recorded on {lender_name} account — "
                                  f"ongoing signs of financial distress"
                              )})

        # --- Active adverse at time of lending (fire once per lender) ---
        if opened and not _adverse_fired:
            active_defaults_at_lending = [
                d for d in full_schema.get("defaults", [])
                if _parse_date(d.get("date")) and _parse_date(d.get("date")) < opened
                and d.get("status") not in ("CCJ", "INSOLVENCY")  # handled separately
            ]
            if active_defaults_at_lending:
                n = len(active_defaults_at_lending)
                adverse_score = 55 if n >= 5 else (45 if n >= 2 else 35)
                score += adverse_score
                _adverse_fired = True
                flags.append({"type": "ACTIVE_ADVERSE_AT_LENDING", "severity": "CRITICAL",
                              "description": (
                                  f"Credit file recorded {n} adverse "
                                  f"{'entry' if n == 1 else 'entries'} before {lender_name} "
                                  f"approved credit on {opened.strftime('%d %b %Y')} — "
                                  f"indicators of existing financial difficulty"
                              )})

        # --- Credit application searches close to lending (fire once per lender) ---
        if opened and not _searches_fired:
            app_searches = _application_searches_within_90_days(searches, opened, exclude_lender=lender_name)
            if app_searches >= 4:
                score += 20
                _searches_fired = True
                flags.append({"type": "MULTIPLE_HARD_SEARCHES", "severity": "HIGH",
                              "description": (
                                  f"{app_searches} confirmed credit application footprints in the "
                                  f"90 days before {lender_name} approved credit — significant "
                                  f"credit-seeking behaviour indicative of financial pressure"
                              )})
            elif app_searches >= 2:
                score += 10
                _searches_fired = True
                flags.append({"type": "HARD_SEARCHES", "severity": "MEDIUM",
                              "description": (
                                  f"{app_searches} credit application searches in the 90 days "
                                  f"before {lender_name} approved credit"
                              )})

    # --- CCJs and public records (global — present on file at time of lending) ---
    all_defs_global = full_schema.get("defaults", [])
    ccj_records = [d for d in all_defs_global if d.get("status") == "CCJ" or d.get("lender", "").upper() == "CCJ"]
    insolvency_records = [d for d in all_defs_global if d.get("status") == "INSOLVENCY"]

    if ccj_records:
        n = len(ccj_records)
        flag_type = "MULTIPLE_CCJS" if n > 1 else "ACTIVE_CCJ"
        # Score only if ACTIVE_ADVERSE_AT_LENDING not already fired (CCJ is a subset of adverse)
        if not _adverse_fired:
            score += 30 if n > 1 else 20
        flags.append({"type": flag_type, "severity": "CRITICAL",
                      "description": (
                          f"{n} County Court Judgment{'s' if n > 1 else ''} registered on file — "
                          f"serious indicator of unresolved financial difficulty at time of lending"
                      )})

    if insolvency_records:
        score += 10
        types_str = ", ".join(
            sorted({d.get("record_type", "PUBLIC_RECORD").replace("_", " ").title()
                    for d in insolvency_records})
        )
        flags.append({"type": "PUBLIC_RECORD_INSOLVENCY", "severity": "HIGH",
                      "description": (
                          f"Public record on file at time of lending: {types_str} — "
                          f"distinguishable from consumer CCJ but a relevant insolvency indicator"
                      )})

    # --- Default registered by this lender ---
    lender_defaults = [d for d in defaults if _lender_match(d.get("lender", ""), lender_name)]
    if lender_defaults:
        score += 20
        flags.append({"type": "DEFAULT_REGISTERED", "severity": "HIGH",
                      "description": f"Default registered by {lender_name} — agreement terminated in arrears"})

    # --- Debt stacking (multiple active accounts at same time) ---
    all_accounts = full_schema.get("accounts", [])
    active_count = sum(1 for a in all_accounts if (a.get("status") or "").upper() == "ACTIVE")
    if len(all_accounts) >= 5:
        score += 15
        flags.append({"type": "DEBT_STACKING", "severity": "MEDIUM",
                      "description": (
                          f"{active_count} active credit facilities identified at date of lending — "
                          f"evidence of debt accumulation across multiple lenders"
                      )})

    # --- Repeat borrowing with same lender ---
    if len(accounts) >= 2:
        score += 15
        flags.append({"type": "REPEAT_BORROWING", "severity": "MEDIUM",
                      "description": f"{len(accounts)} accounts with {lender_name} — repeat subprime lending pattern"})

    # --- Possible debt purchaser (account defaults on or near opening date) ---
    if _is_possible_debt_purchaser(viable_accounts):
        flags.append({"type": "POSSIBLE_DEBT_PURCHASER", "severity": "HIGH",
                      "description": (
                          f"{lender_name}: account defaulted within 31 days of opening — "
                          f"strongly suggests purchased or reassigned debt; manual solicitor review recommended "
                          f"before issuing LOC as {lender_name} may not be the originating lender"
                      )})

    traffic_light = _score_to_traffic_light(score)
    confidence    = _compute_confidence(flags)
    evidence      = _build_evidence_summary(lender_name, flags, score)

    return {
        "traffic_light": traffic_light,
        "score":         min(score, 100),
        "flags":         flags,
        "evidence":      evidence,
        "confidence":    confidence,
    }


def _is_possible_debt_purchaser(accounts: list[dict]) -> bool:
    for acc in accounts:
        opened  = _parse_date(acc.get("opened_date"))
        default = _parse_date(acc.get("default_date"))
        if opened and default:
            if (default - opened).days <= 31:
                return True
    return False


def _score_to_traffic_light(score: int) -> str:
    if score >= GREEN_THRESHOLD:
        return "GREEN"
    elif score >= AMBER_THRESHOLD:
        return "AMBER"
    return "RED"


def _application_searches_within_90_days(searches: list[dict], lending_date: date, exclude_lender: str) -> int:
    """Count only confirmed credit application footprints in the 90-day window before lending."""
    count = 0
    for s in searches:
        s_date = _parse_date(s.get("date"))
        if not s_date:
            continue
        days_before = (lending_date - s_date).days
        if not (0 <= days_before <= 90):
            continue
        if _lender_match(s.get("lender", ""), exclude_lender):
            continue
        # Only count confirmed application footprints; old records without subtype counted for backward compat
        if s.get("search_subtype", None) not in _APPLICATION_SUBTYPES:
            continue
        count += 1
    return count


def _compute_confidence(flags: list[dict]) -> dict:
    """
    Compute a confidence grade based on severity-weighted evidence.
    Reflects legal persuasiveness of the overall flag set, not just volume.
    """
    weight = sum(
        _CONFIDENCE_WEIGHTS.get(f.get("type", "").upper(), 0)
        for f in flags if isinstance(f, dict)
    )
    pct   = min(round(weight / _CONFIDENCE_MAX * 100), 100)
    grade = "High" if pct >= 65 else ("Medium" if pct >= 35 else "Low")
    return {"score": pct, "grade": grade}


def _lender_match(a: str, b: str) -> bool:
    return a.lower().strip() in b.lower().strip() or b.lower().strip() in a.lower().strip()


def _parse_date(val) -> date | None:
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


def _build_evidence_summary(lender_name: str, flags: list[dict], score: int) -> str:
    if not flags:
        return f"No significant affordability indicators identified for {lender_name}."

    critical = [f for f in flags if f.get("severity") == "CRITICAL"]
    high     = [f for f in flags if f.get("severity") == "HIGH"]
    medium   = [f for f in flags if f.get("severity") == "MEDIUM"]

    parts = []
    if critical:
        parts.append("Critical indicators: " + "; ".join(f["description"] for f in critical))
    if high:
        parts.append("High-severity indicators: " + "; ".join(f["description"] for f in high))
    if medium:
        parts.append("Moderate indicators: " + "; ".join(f["description"] for f in medium))

    return " | ".join(parts) + f" (Preliminary claim score: {min(score, 100)}/100)"
