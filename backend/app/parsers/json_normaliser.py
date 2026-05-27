"""
Normalises Equifax and TransUnion JSON partner-post payloads
into the standard Systemize internal schema.

Handles:
  - equifax-sample-partner-post format  (agency: implied by structure)
  - transunion-sample-partner-post format (agency: "TRANSUNION")
  - Combined payload with both bureaus under a single wrapper

Input : parsed JSON dict (from .json file or webhook POST body)
Output: standard schema dict — same shape as normalise_to_schema() in normaliser.py
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def normalise_json_payload(data: dict) -> dict:
    """
    Auto-detect bureau format and return the standard internal schema.
    Raises ValueError for unrecognised payloads.
    """
    agency = (data.get("agency") or "").upper()

    if agency == "TRANSUNION" or _is_transunion(data):
        return _normalise_transunion(data)

    if _is_equifax(data):
        return _normalise_equifax(data)

    # Combined wrapper: {"equifax": {...}, "transunion": {...}}
    if "equifax" in data and "transunion" in data:
        eq = _normalise_equifax(data["equifax"])
        tu = _normalise_transunion(data["transunion"])
        return _merge_bureau_schemas(eq, tu)

    raise ValueError(
        f"Unrecognised JSON partner-post format. "
        f"agency={agency!r}, keys={list(data.keys())[:8]}"
    )


def is_json_partner_post(raw_bytes: bytes) -> bool:
    """Quick check: is this bytes payload a known bureau JSON format?"""
    try:
        data = json.loads(raw_bytes)
        if not isinstance(data, dict):
            return False
        normalise_json_payload(data)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Format detection
# ─────────────────────────────────────────────────────────────────────────────

def _is_transunion(data: dict) -> bool:
    report = data.get("report", {})
    if not isinstance(report, dict):
        return False
    return (
        "FinancialAccountInformation" in report
        or "ElectoralRoll" in report
        or "PersonalInformation" in report
    )


def _is_equifax(data: dict) -> bool:
    report = data.get("report", {})
    if not isinstance(report, dict):
        return False
    inner = report.get("report", {})
    if not isinstance(inner, dict):
        return False
    return "soleSearch" in inner or "nonAddressSpecificData" in inner


# ─────────────────────────────────────────────────────────────────────────────
# Equifax normaliser
# ─────────────────────────────────────────────────────────────────────────────

# insightData key → internal account_type
_EQ_TYPE_MAP = {
    "creditCard":          "CREDIT_CARD",
    "currentAccount":      "CURRENT_ACCOUNT",
    "unsecuredLoan":       "PERSONAL_LOAN",
    "commsSupplyAccount":  "TELECOM",
    "mailOrderAccount":    "MAIL_ORDER",
    "mortgageAccount":     "MORTGAGE",
    "homeCredit":          "HOME_CREDIT",
    "hirePurchase":        "HIRE_PURCHASE",
    "overdraft":           "OVERDRAFT",
    "securedLoan":         "SECURED_LOAN",
}

# Equifax payment status → internal code
_EQ_STATUS_MAP = {
    "ZERO": "0",
    "0":    "0",
    "1":    "1",
    "2":    "2",
    "3":    "3",
    "4":    "4",
    "5":    "5",
    "6":    "6",
    "DEFAULT": "D",
    "D":    "D",
    "S":    "S",
    "U":    "U",
    "N":    "U",
    "Q":    "U",
}


def _normalise_equifax(data: dict) -> dict:
    outer   = data.get("report", {})
    report  = outer.get("report", outer)          # handle both single and double-nested
    client_ref = data.get("clientRefId", "")

    sole      = report.get("soleSearch", {}).get("primary", {})
    supplied  = sole.get("suppliedAddressData", [{}])
    addr_spec = (supplied[0] if supplied else {}).get("addressSpecificData", {})
    insight   = addr_spec.get("insightData", {})
    nad       = report.get("nonAddressSpecificData", {})

    # ── Client ────────────────────────────────────────────────────────────────
    client   = _eq_client(report, addr_spec, client_ref)

    # ── Accounts ──────────────────────────────────────────────────────────────
    accounts = []
    for insight_key, acct_type in _EQ_TYPE_MAP.items():
        for raw_acc in insight.get(insight_key, []):
            acc = _eq_account(raw_acc, acct_type)
            if acc:
                accounts.append(acc)

    # Also check linkedAddressData for additional accounts
    for linked in sole.get("linkedAddressData", []):
        linked_insight = linked.get("addressSpecificData", {}).get("insightData", {})
        for insight_key, acct_type in _EQ_TYPE_MAP.items():
            for raw_acc in linked_insight.get(insight_key, []):
                acc = _eq_account(raw_acc, acct_type)
                if acc:
                    accounts.append(acc)

    # ── Defaults (from payment history D status) ──────────────────────────────
    defaults  = _eq_defaults(accounts, addr_spec)

    # ── Searches ──────────────────────────────────────────────────────────────
    searches  = _eq_searches(report)

    # ── Risk flags (CCJ, CIFAS, insolvency) ───────────────────────────────────
    risk_flags = _eq_risk_flags(addr_spec)

    # ── Credit score ──────────────────────────────────────────────────────────
    scores_raw = nad.get("scores", {}).get("score", [])
    credit_score = scores_raw[0].get("value") if scores_raw else None

    return {
        "client":       client,
        "accounts":     accounts,
        "searches":     searches,
        "defaults":     defaults,
        "risk_flags":   risk_flags,
        "credit_score": credit_score,
        "_source":      "EQUIFAX",
    }


def _eq_client(report: dict, addr_spec: dict, client_ref: str) -> dict:
    # Name/DOB live inside account records for Equifax
    nad = report.get("nonAddressSpecificData", {})
    sole = report.get("soleSearch", {}).get("primary", {})
    supplied = sole.get("suppliedAddressData", [{}])

    # Try to get name from first alias or first account record
    name = ""
    aliases = nad.get("aliases", {}).get("alias", [])
    if aliases:
        alias_name = aliases[0].get("aliasName", [])
        if alias_name:
            name = alias_name[0]

    dob = ""
    if aliases:
        dob = aliases[0].get("dob", "")

    # Fall back to extracting from insight account records
    if not name:
        insight = addr_spec.get("insightData", {})
        for key in _EQ_TYPE_MAP:
            recs = insight.get(key, [])
            if recs:
                rec_name = recs[0].get("name", {})
                parts = [
                    rec_name.get("forename", ""),
                    rec_name.get("middleName", ""),
                    rec_name.get("surname", ""),
                ]
                name = " ".join(p for p in parts if p).strip()
                dob  = recs[0].get("dob", dob)
                break

    # Address from supplied address
    address = ""
    if supplied:
        addr_obj = supplied[0].get("address", {})
        if isinstance(addr_obj, dict):
            parts = [
                addr_obj.get("houseNumber", ""),
                addr_obj.get("houseName", ""),
                addr_obj.get("streetName", ""),
                addr_obj.get("district", ""),
                addr_obj.get("town", ""),
                addr_obj.get("postCode", ""),
            ]
            address = ", ".join(p for p in parts if p)

    report_date = report.get("ReportDetails", {}).get("DateOfReport", "")

    return {
        "name":        name,
        "dob":         _fmt_date(dob),
        "address":     address,
        "matter_ref":  client_ref or "",
        "report_date": _fmt_date(report_date),
    }


def _eq_account(raw: dict, acct_type: str) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    company = raw.get("companyName", "Unknown").strip().lstrip("-").strip()
    acct_no = str(raw.get("accountNumber", "") or "")

    # Balance
    bal_obj = raw.get("currentBalance", {}).get("balanceAmount", {})
    balance = _safe_amount(bal_obj)

    # Default balance
    def_bal_obj = raw.get("defaultBalance", {}).get("balanceAmount", {})
    default_balance = _safe_amount(def_bal_obj)

    # Credit limit
    lim_obj = raw.get("creditLimit", {}).get("limit", {})
    credit_limit = _safe_amount(lim_obj)

    # Utilisation
    utilisation = None
    if credit_limit and credit_limit > 0 and balance is not None:
        utilisation = round((balance / credit_limit) * 100, 1)

    # Dates
    start_date   = _fmt_date(raw.get("startDate", ""))
    end_date     = _fmt_date(raw.get("endDate", ""))
    last_updated = _fmt_date(raw.get("lastUpdateDate", ""))

    # Payment history — list of status codes ordered oldest→newest (ageInMonths desc→asc)
    raw_history  = raw.get("paymentHistory", [])
    # Sort by ageInMonths descending so index 0 = oldest
    raw_history  = sorted(raw_history, key=lambda x: x.get("ageInMonths", 0), reverse=True)
    payment_hist = [
        _EQ_STATUS_MAP.get(str(p.get("paymentStatus", "U")).upper(), "U")
        for p in raw_history
    ]

    # Derive overall status from most-recent payment entry and default balance
    status = "ACTIVE"
    if default_balance and default_balance > 0:
        status = "DEFAULT"
    elif end_date:
        status = "SETTLED"
    elif payment_hist:
        last = payment_hist[-1]  # most recent (ageInMonths=0)
        if last == "D":
            status = "DEFAULT"
        elif last == "S":
            status = "SETTLED"

    # Default date — find first DEFAULT in history (from most recent backward)
    default_date = None
    if status == "DEFAULT" and raw_history:
        for ph in raw_history:  # sorted oldest→newest above
            if _EQ_STATUS_MAP.get(str(ph.get("paymentStatus", "")).upper()) == "D":
                # Approximate default date from ageInMonths + lastUpdateDate
                age = ph.get("ageInMonths", 0)
                if last_updated:
                    try:
                        lu = datetime.strptime(last_updated, "%Y-%m-%d").date()
                        from dateutil.relativedelta import relativedelta  # type: ignore
                        default_date = str(lu - relativedelta(months=age))
                    except Exception:
                        pass
                break

    # Fixed payment terms
    fixed = raw.get("fixedPaymentTerms", {})
    monthly_payment = _safe_amount(fixed.get("paymentAmount", {}))

    return {
        "lender":          company,
        "account_type":    acct_type,
        "account_number":  acct_no,
        "opened_date":     start_date,
        "closed_date":     end_date,
        "balance":         balance,
        "credit_limit":    credit_limit,
        "utilisation_pct": utilisation,
        "status":          status,
        "default_date":    default_date,
        "default_balance": default_balance,
        "monthly_payment": monthly_payment,
        "payment_history": payment_hist,
        "last_updated":    last_updated,
    }


def _eq_defaults(accounts: list, addr_spec: dict) -> list:
    defaults = []

    # From defaulted accounts
    for acc in accounts:
        if acc.get("status") in ("DEFAULT", "DEFAULTED"):
            defaults.append({
                "lender": acc["lender"],
                "date":   acc.get("default_date") or acc.get("opened_date", ""),
                "amount": acc.get("default_balance") or acc.get("balance") or 0,
                "status": "active" if not acc.get("closed_date") else "satisfied",
            })

    # From courtAndInsolvencyInformation (CCJs are separate but recorded here)
    court_recs = addr_spec.get("courtAndInsolvencyInformationData", {}).get(
        "courtAndInsolvencyInformation", []
    )
    for rec in court_recs:
        ccj_type = rec.get("ccjType", "")
        amount   = (rec.get("value") or {}).get("amount", 0)
        court_dt = _fmt_date(rec.get("courtDate", ""))
        defaults.append({
            "lender":  rec.get("courtName", "Court"),
            "date":    court_dt,
            "amount":  amount,
            "status":  "CCJ",
        })

    return defaults


def _eq_searches(report: dict) -> list:
    searches = []
    # Equifax search records live under soleSearch.primary.searches (if present)
    search_data = (
        report.get("soleSearch", {})
        .get("primary", {})
        .get("searchData", {})
        .get("searches", [])
    )
    for s in search_data:
        searches.append({
            "date":         _fmt_date(s.get("date", "")),
            "lender":       s.get("companyName", ""),
            "search_type":  "HARD" if s.get("searchType", "").upper() in ("A", "FULL", "APPLICATION") else "SOFT",
            "search_subtype": "APPLICATION",
        })
    return searches


def _eq_risk_flags(addr_spec: dict) -> list:
    flags = []

    # CIFAS
    for cifas in addr_spec.get("cifasData", {}).get("cifas", []):
        reasons = [r.get("_", r.get("id", "")) for r in cifas.get("filingReason", [])]
        flags.append({
            "flag_type":   "CIFAS",
            "description": f"CIFAS marker: {cifas.get('caseType', '')} — {', '.join(str(r) for r in reasons)}",
            "severity":    "HIGH",
            "date":        _fmt_date(cifas.get("fraudDate", "") or cifas.get("applicationDate", "")),
        })

    # CCJs / insolvency (court records)
    for rec in addr_spec.get("courtAndInsolvencyInformationData", {}).get(
        "courtAndInsolvencyInformation", []
    ):
        ccj_type = rec.get("ccjType", "CCJ")
        amount   = (rec.get("value") or {}).get("amount", 0)
        flags.append({
            "flag_type":   "CCJ",
            "description": f"County Court Judgment ({ccj_type}): £{amount} at {rec.get('courtName', '')}",
            "severity":    "HIGH",
            "date":        _fmt_date(rec.get("courtDate", "")),
        })

    return flags


# ─────────────────────────────────────────────────────────────────────────────
# TransUnion normaliser
# ─────────────────────────────────────────────────────────────────────────────

# TransUnion AccountTypeCode → internal account_type
_TU_TYPE_MAP = {
    "CC":  "CREDIT_CARD",
    "ST":  "STORE_CARD",
    "MG":  "MORTGAGE",
    "PL":  "PERSONAL_LOAN",
    "HL":  "HOME_CREDIT",
    "HP":  "HIRE_PURCHASE",
    "CA":  "CURRENT_ACCOUNT",
    "OD":  "OVERDRAFT",
    "SL":  "SECURED_LOAN",
    "UT":  "UTILITY",
    "TL":  "TELECOM",
    "OT":  "OTHER",
}

# TransUnion payment status → internal code
_TU_STATUS_MAP = {
    "0":    "0",
    "OK":   "0",
    "1":    "1",
    "2":    "2",
    "3":    "3",
    "4":    "4",
    "5":    "5",
    "6":    "6",
    "DF":   "D",
    "D":    "D",
    "DEFAULT": "D",
    "S":    "S",
    "U":    "U",
    "N":    "U",
}


def _normalise_transunion(data: dict) -> dict:
    report     = data.get("report", {})
    client_ref = data.get("clientRefId", "")

    client    = _tu_client(report, client_ref)
    accounts  = _tu_accounts(report)
    defaults  = _tu_defaults(report, accounts)
    searches  = _tu_searches(report)
    risk_flags = _tu_risk_flags(report)

    # Credit score
    rating = report.get("Rating", {})
    credit_score = rating.get("Score")

    return {
        "client":       client,
        "accounts":     accounts,
        "searches":     searches,
        "defaults":     defaults,
        "risk_flags":   risk_flags,
        "credit_score": credit_score,
        "_source":      "TRANSUNION",
    }


def _tu_client(report: dict, client_ref: str) -> dict:
    pi = report.get("PersonalInformation", {})
    report_date = report.get("ReportDetails", {}).get("DateOfReport", "")
    return {
        "name":        pi.get("Name", ""),
        "dob":         _fmt_date(pi.get("DateOfBirth", "")),
        "address":     pi.get("CurrentAddress", ""),
        "matter_ref":  client_ref or "",
        "report_date": _fmt_date(report_date),
        "email":       pi.get("email", ""),
        "mobile":      pi.get("mobile", ""),
    }


def _tu_accounts(report: dict) -> list:
    fai      = report.get("FinancialAccountInformation", {})
    moda     = report.get("Moda", {})
    accounts = []

    # Standard account categories
    for category, default_type in [
        ("CreditCards",    "CREDIT_CARD"),
        ("Mortgages",      "MORTGAGE"),
        ("PersonalLoans",  "PERSONAL_LOAN"),
        ("OtherAccounts",  "OTHER"),
        ("ClosedAccounts", None),          # type determined per-record
    ]:
        for raw in fai.get(category, []):
            acc = _tu_account(raw, default_type)
            if acc:
                accounts.append(acc)

    # Moda accounts (payday / high-cost short-term lenders)
    for raw in moda.get("Accounts", []) + moda.get("ClosedAccounts", []):
        acc = _tu_moda_account(raw)
        if acc:
            accounts.append(acc)

    return accounts


def _tu_account(raw: dict, default_type: Optional[str]) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    lender     = raw.get("LenderName", "Unknown")
    type_code  = raw.get("AccountTypeCode", "")
    acct_type  = _TU_TYPE_MAP.get(type_code.upper(), default_type or "OTHER")
    acct_no    = raw.get("AccountNumber", "")

    balance       = _coerce_num(raw.get("Balance"))
    opening_bal   = _coerce_num(raw.get("OpeningBalance"))
    default_bal   = _coerce_num(raw.get("DefaultBalance"))
    min_payment   = _coerce_num(raw.get("MinimumPayment"))
    reg_payment   = _coerce_num(raw.get("RegularPaymentAmount"))

    # Credit limit — from LimitHistory (most recent)
    credit_limit = _tu_latest_limit(raw.get("LimitHistory", []))

    # Utilisation
    utilisation = None
    if credit_limit and credit_limit > 0 and balance is not None:
        utilisation = round((balance / credit_limit) * 100, 1)

    # Dates
    start_date   = _fmt_date(raw.get("AccountStartDate", ""))
    end_date     = _fmt_date(raw.get("AccountEndDate", ""))
    default_date = _fmt_date(raw.get("DefaultDate", ""))
    updated_date = _fmt_date(raw.get("UpdatedDate", ""))

    # Status
    status_raw = (raw.get("Status") or raw.get("StatusSubjectiveLevel") or "").upper()
    if default_bal and default_bal > 0:
        status = "DEFAULT"
    elif status_raw in ("CLOSED", "SETTLED", "SATISFIED"):
        status = "SETTLED"
    elif status_raw in ("DEFAULT", "DEFAULTED"):
        status = "DEFAULT"
    else:
        status = "ACTIVE"

    # Payment history — flatten StatusHistory into ordered list
    payment_hist = _tu_payment_history(raw.get("StatusHistory", []))

    return {
        "lender":          lender,
        "account_type":    acct_type,
        "account_number":  str(acct_no or ""),
        "opened_date":     start_date,
        "closed_date":     end_date,
        "balance":         balance,
        "credit_limit":    credit_limit,
        "utilisation_pct": utilisation,
        "status":          status,
        "default_date":    default_date,
        "default_balance": default_bal,
        "monthly_payment": reg_payment or min_payment,
        "payment_history": payment_hist,
        "last_updated":    updated_date,
    }


def _tu_moda_account(raw: dict) -> Optional[dict]:
    """Handle TransUnion Moda (payday/high-cost) accounts."""
    if not isinstance(raw, dict):
        return None

    lender    = raw.get("OrganisationName", "Unknown")
    org_type  = raw.get("OrganisationType", "")
    freq      = raw.get("RepaymentFrequency", "")

    # Classify as PAYDAY_LOAN when weekly repayment or known finance org
    acct_type = "PAYDAY_LOAN" if freq.upper() in ("WEEKLY", "W") else "HIGH_COST_LOAN"

    balance      = _coerce_num(raw.get("Balance"))
    credit_limit = _coerce_num(raw.get("Limit"))
    utilisation  = None
    if credit_limit and credit_limit > 0 and balance is not None:
        utilisation = round((balance / credit_limit) * 100, 1)

    start_date   = _fmt_date(raw.get("StartDate", ""))
    end_date     = _fmt_date(raw.get("EndDate", ""))
    default_date = None

    overdue = _coerce_num(raw.get("OverduePaymentsCount")) or 0
    rolled  = raw.get("IsRolledOver", False)
    extended = raw.get("HasCreditExtension", False)

    status = "ACTIVE"
    if end_date:
        status = "SETTLED"
    if overdue > 0:
        status = "DEFAULT" if not end_date else "SETTLED"

    payment_hist = ["3" if overdue > 0 else "0"] * max(1, int(overdue or 1))

    risk_note = []
    if rolled:
        risk_note.append("ROLLED_OVER")
    if extended:
        risk_note.append("CREDIT_EXTENSION")

    return {
        "lender":          lender,
        "account_type":    acct_type,
        "account_number":  "",
        "opened_date":     start_date,
        "closed_date":     end_date,
        "balance":         balance,
        "credit_limit":    credit_limit,
        "utilisation_pct": utilisation,
        "status":          status,
        "default_date":    default_date,
        "default_balance": balance if overdue > 0 else None,
        "monthly_payment": None,
        "payment_history": payment_hist,
        "last_updated":    None,
        "risk_notes":      risk_note,
    }


def _tu_payment_history(status_history: list) -> list:
    """
    Flatten TransUnion StatusHistory (year/month nested) into a flat list
    of internal status codes, ordered oldest→newest.
    """
    if not status_history:
        return []

    # Each entry: {"Year": 2021, "MonthlyStatusHistory": [{Month, PaymentStatus, ...}]}
    monthly = []
    for year_rec in sorted(status_history, key=lambda x: x.get("Year", 0)):
        year = year_rec.get("Year", 0)
        for month_rec in sorted(
            year_rec.get("MonthlyStatusHistory", []),
            key=lambda x: x.get("Month", 0)
        ):
            raw_status = str(month_rec.get("PaymentStatus", "U")).upper()
            internal   = _TU_STATUS_MAP.get(raw_status, "U")
            monthly.append(internal)

    return monthly


def _tu_latest_limit(limit_history: list) -> Optional[float]:
    """Extract the most recent credit limit value from LimitHistory."""
    if not limit_history:
        return None
    flat = []
    for year_rec in limit_history:
        year = year_rec.get("Year", 0)
        for entry in year_rec.get("MonthHistory", []):
            flat.append((year, entry.get("Month", 0), entry.get("Value")))
    if not flat:
        return None
    flat.sort(reverse=True)
    val = flat[0][2]
    return _coerce_num(val)


def _tu_defaults(report: dict, accounts: list) -> list:
    defaults = []

    # From defaulted accounts
    for acc in accounts:
        if acc.get("status") in ("DEFAULT", "DEFAULTED"):
            defaults.append({
                "lender": acc["lender"],
                "date":   acc.get("default_date") or acc.get("opened_date", ""),
                "amount": acc.get("default_balance") or acc.get("balance") or 0,
                "status": "active" if not acc.get("closed_date") else "satisfied",
            })

    # From PublicInformation.Judgments
    for jdg in report.get("PublicInformation", {}).get("Judgments", []):
        defaults.append({
            "lender":  jdg.get("CourtName", "Court"),
            "date":    _fmt_date(jdg.get("JudgmentDate", "") or jdg.get("OrderDate", "")),
            "amount":  _coerce_num(jdg.get("Amount")) or 0,
            "status":  "CCJ",
        })

    # From PublicInformation.Insolvencies
    for ins in report.get("PublicInformation", {}).get("Insolvencies", []):
        status_flag = "INSOLVENCY_SATISFIED" if ins.get("Status", "").lower() == "satisfied" else "INSOLVENCY"
        defaults.append({
            "lender":  ins.get("CourtName", "Court"),
            "date":    _fmt_date(ins.get("OrderDate", "")),
            "amount":  0,
            "status":  status_flag,
            "type":    ins.get("OrderTypeName", "Insolvency"),
        })

    return defaults


def _tu_searches(report: dict) -> list:
    """TransUnion search records (may not be present in all payloads)."""
    searches = []
    search_data = report.get("Searches", report.get("SearchHistory", []))
    if isinstance(search_data, dict):
        search_data = search_data.get("Records", [])
    for s in search_data:
        search_type = (s.get("SearchType") or s.get("Type") or "").upper()
        is_hard = search_type in ("FULL", "APPLICATION", "HARD", "A")
        searches.append({
            "date":           _fmt_date(s.get("Date") or s.get("SearchDate", "")),
            "lender":         s.get("MemberName") or s.get("CompanyName", ""),
            "search_type":    "HARD" if is_hard else "SOFT",
            "search_subtype": "APPLICATION" if is_hard else "QUOTATION",
        })
    return searches


def _tu_risk_flags(report: dict) -> list:
    flags = []

    # CIFAS
    for case in report.get("Cifas", {}).get("CifasCases", []):
        flags.append({
            "flag_type":   "CIFAS",
            "description": f"CIFAS case: {case.get('CaseType', '')} — {case.get('ProductType', '')}",
            "severity":    "HIGH",
            "date":        _fmt_date(case.get("ApplicationDate", "") or case.get("FraudDate", "")),
        })

    # Insolvencies
    for ins in report.get("PublicInformation", {}).get("Insolvencies", []):
        satisfied = ins.get("Status", "").lower() == "satisfied"
        flags.append({
            "flag_type":   "INSOLVENCY",
            "description": (
                f"{ins.get('OrderTypeName', 'Insolvency')} at {ins.get('CourtName', 'Court')} "
                f"({'Satisfied' if satisfied else 'Active'})"
            ),
            "severity":    "MEDIUM" if satisfied else "HIGH",
            "date":        _fmt_date(ins.get("OrderDate", "")),
        })

    # Judgments / CCJs
    for jdg in report.get("PublicInformation", {}).get("Judgments", []):
        flags.append({
            "flag_type":   "CCJ",
            "description": f"County Court Judgment: £{_coerce_num(jdg.get('Amount', 0))} at {jdg.get('CourtName', '')}",
            "severity":    "HIGH",
            "date":        _fmt_date(jdg.get("JudgmentDate", "") or jdg.get("OrderDate", "")),
        })

    # Notices of Correction
    for noc in report.get("NoticesOfCorrection", {}).get("Records", []):
        flags.append({
            "flag_type":   "NOTICE_OF_CORRECTION",
            "description": noc.get("Text", "Notice of correction on file"),
            "severity":    "LOW",
            "date":        None,
        })

    return flags


# ─────────────────────────────────────────────────────────────────────────────
# Merge two bureau schemas (for combined Equifax + TransUnion payloads)
# ─────────────────────────────────────────────────────────────────────────────

def _merge_bureau_schemas(eq: dict, tu: dict) -> dict:
    """
    Merge Equifax and TransUnion schemas for the same client.
    TransUnion personal info is preferred (has structured PersonalInformation).
    Accounts and risk flags are combined and deduplicated by lender+type+date.
    """
    # Client: prefer TU (cleaner personal info), fill gaps from EQ
    client = dict(tu.get("client", {}))
    eq_client = eq.get("client", {})
    for k in ("name", "dob", "address", "matter_ref"):
        if not client.get(k) and eq_client.get(k):
            client[k] = eq_client[k]

    # Credit score: prefer TU score, keep EQ as secondary
    credit_score = tu.get("credit_score") or eq.get("credit_score")

    # Accounts: combine, using lender+type as dedup key
    seen = set()
    accounts = []
    for acc in (tu.get("accounts", []) + eq.get("accounts", [])):
        key = (
            (acc.get("lender") or "").upper().strip(),
            acc.get("account_type", ""),
            acc.get("opened_date", ""),
        )
        if key not in seen:
            seen.add(key)
            accounts.append(acc)

    # Defaults, searches, risk_flags: combine all
    defaults   = tu.get("defaults",   []) + eq.get("defaults",   [])
    searches   = tu.get("searches",   []) + eq.get("searches",   [])
    risk_flags = tu.get("risk_flags", []) + eq.get("risk_flags", [])

    return {
        "client":       client,
        "accounts":     accounts,
        "searches":     searches,
        "defaults":     defaults,
        "risk_flags":   risk_flags,
        "credit_score": credit_score,
        "_source":      "EQUIFAX+TRANSUNION",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_date(val: Any) -> str:
    """Normalise any date-ish value to YYYY-MM-DD string or empty string."""
    if not val:
        return ""
    if isinstance(val, (date, datetime)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    # ISO datetime with T
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    # DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # YYYY/MM/DD
    m = re.match(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    return ""


def _coerce_num(val: Any) -> Optional[float]:
    """Safely coerce to float, returning None on failure."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        # Equifax amount objects: {"amount": 1400, "currency": "GBP"}
        return _coerce_num(val.get("amount") or val.get("balanceAmount") or val.get("limit"))
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _safe_amount(obj: Any) -> Optional[float]:
    """Extract numeric value from Equifax nested amount objects."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return _coerce_num(obj.get("amount") or obj.get("limit"))
    return _coerce_num(obj)
