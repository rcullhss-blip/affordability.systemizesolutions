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

    # Valid8 / TSL multi-bureau partner payload (Woodville)
    if _is_valid8(data):
        return _normalise_valid8(data)

    # Full Experian/TransUnion bureau report (Woodville — results[].provider)
    if _is_bureau_results(data):
        return _normalise_bureau_report(data)

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


def _is_valid8(data: dict) -> bool:
    """Valid8 / TSL multi-bureau payload — has an all_accounts list and a request block."""
    return isinstance(data.get("all_accounts"), list) and isinstance(data.get("request"), dict)


# ─────────────────────────────────────────────────────────────────────────────
# Valid8 / TSL multi-bureau normaliser (Woodville)
# ─────────────────────────────────────────────────────────────────────────────

_V8_TYPE_MAP = {
    "personal_loan": "PERSONAL_LOAN", "unsecured_loan": "PERSONAL_LOAN", "loan": "PERSONAL_LOAN",
    "fixed_term_loan": "PERSONAL_LOAN", "guarantor_loan": "PERSONAL_LOAN",
    "credit_card": "CREDIT_CARD", "charge_card": "CREDIT_CARD", "store_card": "STORE_CARD",
    "hire_purchase": "HIRE_PURCHASE", "conditional_sale": "HIRE_PURCHASE", "motor_finance": "HIRE_PURCHASE",
    "mail_order": "MAIL_ORDER", "catalogue": "MAIL_ORDER", "home_credit": "HOME_CREDIT",
    "payday": "PAYDAY_LOAN", "payday_loan": "PAYDAY_LOAN", "short_term_loan": "PAYDAY_LOAN",
    "hcstc": "PAYDAY_LOAN", "current_account": "CURRENT_ACCOUNT", "bank_account": "CURRENT_ACCOUNT",
    "overdraft": "OVERDRAFT", "mortgage": "MORTGAGE", "communications": "TELECOM",
    "telecom": "TELECOM", "utility": "UTILITY", "other": "OTHER",
}

# account_status values (and CAIS status codes) that indicate adverse / default
_V8_DEFAULT_STATUSES = {"default", "defaulted", "delinquent", "in_arrears", "arrears",
                        "debt_management", "gone_away"}
_V8_DEFAULT_CODES = {"D", "8"}  # CAIS: 8 = default, D = default


def _v8_type(t: str) -> str:
    return _V8_TYPE_MAP.get((t or "").lower().strip(), "OTHER")


def _v8_amount(v):
    try:
        return float(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _normalise_valid8(data: dict) -> dict:
    req = data.get("request", {}) or {}
    pd  = req.get("personal_details", {}) or {}
    ad  = req.get("current_address", {}) or {}

    name = " ".join(
        str(x).strip() for x in
        (pd.get("title"), pd.get("first_name"), pd.get("middle_name"), pd.get("last_name"))
        if x and str(x).strip()
    )
    addr_parts = [ad.get("building_number"), ad.get("building_name"), ad.get("sub_building_name"),
                  ad.get("flat"), ad.get("line1"), ad.get("line2"), ad.get("street"),
                  ad.get("post_town"), ad.get("county"), ad.get("postcode")]
    address = ", ".join(str(p).strip() for p in addr_parts if p and str(p).strip())

    client = {
        "name":       name,
        "dob":        pd.get("date_of_birth") or "",
        "address":    address,
        "email":      pd.get("email") or "",
        "phone":      pd.get("mobile_number") or pd.get("landline_number") or "",
        "matter_ref": data.get("client_reference") or data.get("provider_reference") or "",
    }

    accounts, defaults = [], []
    for a in data.get("all_accounts", []) or []:
        status_raw = (a.get("account_status") or "").lower().strip()
        code       = (a.get("account_status_code") or "").upper().strip()
        is_default = status_raw in _V8_DEFAULT_STATUSES or code in _V8_DEFAULT_CODES
        status = "SETTLED" if status_raw == "settled" else ("DEFAULT" if is_default else "ACTIVE")

        lender  = a.get("lender_name_credit") or a.get("lender_name_frontend") or "Unknown"
        opened  = a.get("account_start_date") or ""
        settled = a.get("account_settlement_date") or ""
        bal     = _v8_amount(a.get("current_balance"))
        # Valid8 gives no explicit default date; use settlement date as a proxy when defaulted
        default_date = (a.get("account_default_date") or (settled if is_default else None)) or None
        default_balance = bal if is_default else None

        accounts.append({
            "lender":          lender,
            "account_type":    _v8_type(a.get("account_type")),
            "account_number":  a.get("account_number") or "",
            "opened_date":     opened,
            "closed_date":     settled,
            "balance":         bal if bal is not None else 0.0,
            "credit_limit":    None,
            "utilisation_pct": None,
            "status":          status,
            "default_date":    default_date,
            "default_balance": default_balance,
            "monthly_payment": _v8_amount(a.get("payment_amount")),
            "payment_history": [],   # not provided by this Valid8 view
            "last_updated":    None,
        })
        if is_default:
            defaults.append({"lender": lender, "status": "DEFAULT",
                             "amount": default_balance or 0, "date": default_date})

    return {
        "client":       client,
        "accounts":     accounts,
        "searches":     [],
        "defaults":     defaults,
        "risk_flags":   [],
        "credit_score": None,
        "_source":      "VALID8",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Full Experian / TransUnion bureau report (Woodville — results[].provider)
# ─────────────────────────────────────────────────────────────────────────────

# Experian CAIS account-type codes → internal type
_EXP_CODE_MAP = {
    "00": "CURRENT_ACCOUNT", "01": "CREDIT_CARD", "02": "PERSONAL_LOAN", "03": "HIRE_PURCHASE",
    "04": "PERSONAL_LOAN", "05": "OTHER", "06": "MORTGAGE", "07": "MAIL_ORDER", "08": "OTHER",
    "09": "OTHER", "10": "CREDIT_CARD", "16": "OTHER", "17": "OTHER", "19": "HIRE_PURCHASE",
    "22": "TELECOM", "23": "UTILITY", "26": "PAYDAY_LOAN", "37": "STORE_CARD",
}


def _is_bureau_results(data: dict) -> bool:
    res = data.get("results")
    if isinstance(res, list) and any(
        isinstance(r, dict) and r.get("provider") in ("Experian", "TransUnion") for r in res
    ):
        return True
    # single-report wrappers (kycResult / result, no results[] array)
    return bool(_find_all(data, "caisDetails", []) or _find_all(data, "financialAccountInformation", []))


def _find_all(o, key, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                out.append(v)
            _find_all(v, key, out)
    elif isinstance(o, list):
        for v in o:
            _find_all(v, key, out)
    return out


def _exp_date(obj) -> str:
    if not isinstance(obj, dict) or not obj.get("ccyySpecified"):
        return ""
    y, m, d = obj.get("ccyy"), obj.get("mm") or 1, obj.get("dd") or 1
    try:
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except (TypeError, ValueError):
        return ""


def _exp_type(code: str) -> str:
    return _EXP_CODE_MAP.get((str(code or "").strip()), "OTHER")


def _exp_balance(raw: dict) -> float:
    bals = raw.get("accountBalances") or []
    if bals:
        try:
            return float(int(bals[0].get("accountBalance", "0")))
        except (TypeError, ValueError):
            pass
    return 0.0


def _normalise_experian_report(data: dict) -> dict:
    # Works for both the results[]-array wrapper and the kycResult/result wrapper:
    # we search the whole payload for the Experian CAIS structures.
    exp = data

    # ── Client (applicant + address) ──────────────────────────────────────────
    apps = _find_all(exp, "applicant", [])
    app = {}
    for a in apps:
        cand = a[0] if isinstance(a, list) and a else a
        if isinstance(cand, dict) and cand.get("name"):
            app = cand; break
    nm = app.get("name", {}) if isinstance(app, dict) else {}
    name = " ".join(x for x in (nm.get("title"), nm.get("forename"), nm.get("surname")) if x) \
        or app.get("formattedName", "")
    dob = app.get("formattedDOB", "") or _exp_date(app.get("dateOfBirth"))

    address = ""
    for loc in _find_all(exp, "locationDetails", []):
        cand = loc[0] if isinstance(loc, list) and loc else loc
        uk = (cand or {}).get("ukLocation") if isinstance(cand, dict) else None
        if uk:
            parts = [uk.get("houseNumber"), uk.get("flat"), uk.get("street"), uk.get("district"),
                     uk.get("postTown"), uk.get("county"), uk.get("postcode")]
            address = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
            break

    client = {
        "name": name.strip(), "dob": dob, "address": address,
        "email": "", "phone": "",
        "matter_ref": data.get("clientReference") or exp.get("clientReference") or "",
    }

    # ── Accounts (CAIS) ──────────────────────────────────────────────────────
    accounts, defaults = [], []
    cais_accounts = []
    for cd in _find_all(exp, "caisDetails", []):
        if isinstance(cd, list):
            cais_accounts.extend(x for x in cd if isinstance(x, dict))

    for raw in cais_accounts:
        lender  = (raw.get("supplyCompanyName") or "Unknown").strip()
        opened  = _exp_date(raw.get("caisAccStartDate"))
        settled = _exp_date(raw.get("settlementDate"))
        last_up = _exp_date(raw.get("lastUpdatedDate"))
        codes   = (raw.get("accountStatusCodes") or "").strip()
        acc_status = (raw.get("accountStatus") or "").upper().strip()
        worst   = (raw.get("worstStatus") or "").upper().strip()

        # payment history: keep month codes, map default marker 8 → D
        payment_hist = [("D" if c == "8" else c) for c in codes if c not in (" ", "U", "")]

        is_default = ("8" in codes) or ("D" in codes) or acc_status in ("D", "8") or worst in ("8", "D")
        default_date = None
        if is_default:
            # accountStatusCodes is most-recent-month-first. The account first
            # defaulted at the OLDEST month of the current run of 8/D markers.
            first8 = next((i for i, c in enumerate(codes) if c in ("8", "D")), None)
            run_end = first8
            if first8 is not None:
                j = first8
                while j + 1 < len(codes) and codes[j + 1] in ("8", "D"):
                    j += 1
                run_end = j
            base = None
            if last_up:
                try:
                    base = datetime.strptime(last_up, "%Y-%m-%d").date()
                except ValueError:
                    base = None
            if run_end is not None and base is not None:
                from dateutil.relativedelta import relativedelta
                default_date = str(base - relativedelta(months=run_end))
            else:
                default_date = settled or opened or None

        balance = _exp_balance(raw)
        if raw.get("balance", {}).get("narrative") == "S" or (settled and not is_default):
            status = "SETTLED"
            balance = 0.0
        elif is_default:
            status = "DEFAULT"
        else:
            status = "ACTIVE"

        pay = raw.get("payment", "")
        monthly = None
        m = re.search(r"([\d,]+)", pay.replace("£", "")) if isinstance(pay, str) else None
        if m:
            try: monthly = float(m.group(1).replace(",", ""))
            except ValueError: pass

        accounts.append({
            "lender": lender, "account_type": _exp_type(raw.get("accountType")),
            "account_number": raw.get("accountNumber") or "", "opened_date": opened,
            "closed_date": settled, "balance": balance, "credit_limit": None,
            "utilisation_pct": None, "status": status, "default_date": default_date,
            "default_balance": (balance if is_default else None), "monthly_payment": monthly,
            "payment_history": payment_hist, "last_updated": last_up,
        })
        if is_default:
            defaults.append({"lender": lender, "status": "DEFAULT",
                             "amount": balance or 0, "date": default_date})

    return {
        "client": client, "accounts": accounts, "searches": [], "defaults": defaults,
        "risk_flags": [], "credit_score": None, "_source": "EXPERIAN_REPORT",
    }


# TransUnion (camelCase, nested under jsonReport.report) — Woodville variant
_TU_CAMEL_CATEGORIES = [
    ("creditCards", "CREDIT_CARD"), ("personalLoans", "PERSONAL_LOAN"),
    ("mortgages", "MORTGAGE"), ("otherAccounts", "OTHER"),
    ("hirePurchase", "HIRE_PURCHASE"), ("mailOrder", "MAIL_ORDER"),
    ("communications", "TELECOM"), ("closedAccounts", None),
]


def _first(raw: dict, *keys):
    for k in keys:
        v = raw.get(k)
        if v not in (None, ""):
            return v
    return None


def _tu_account_camel(raw: dict, default_type):
    if not isinstance(raw, dict):
        return None
    lender = _first(raw, "lenderName", "companyName", "supplierName", "name") or "Unknown"
    acc_type = _V8_TYPE_MAP.get(str(_first(raw, "accountType") or "").lower().strip(),
                               default_type or "OTHER")
    balance     = _v8_amount(_first(raw, "balance", "currentBalance", "outstandingBalance"))
    default_bal = _v8_amount(_first(raw, "defaultBalance", "defaultedBalance"))
    start_date  = _fmt_date(_first(raw, "accountStartDate", "startDate", "openDate") or "")
    end_date    = _fmt_date(_first(raw, "accountEndDate", "settlementDate", "closedDate") or "")
    default_date = _fmt_date(_first(raw, "defaultDate", "defaultedDate") or "")
    status_raw  = str(_first(raw, "status", "accountStatus", "statusSubjectiveLevel") or "").upper()

    if default_date or (default_bal and default_bal > 0) or status_raw in ("DEFAULT", "DEFAULTED"):
        status = "DEFAULT"
    elif status_raw in ("CLOSED", "SETTLED", "SATISFIED") or end_date:
        status = "SETTLED"
    else:
        status = "ACTIVE"

    # payment history: accept a flat status string or a list of month codes
    ph_raw = _first(raw, "paymentHistory", "statusHistory", "accountStatusHistory")
    payment_hist = []
    if isinstance(ph_raw, str):
        payment_hist = [("D" if c == "8" else c) for c in ph_raw if c not in (" ", "U", "")]
    elif isinstance(ph_raw, list):
        for e in ph_raw:
            v = e.get("status") if isinstance(e, dict) else e
            if v not in (None, ""):
                payment_hist.append("D" if str(v) == "8" else str(v))

    return {
        "lender": lender, "account_type": acc_type,
        "account_number": str(_first(raw, "accountNumber", "accountRef") or ""),
        "opened_date": start_date, "closed_date": end_date,
        "balance": balance if balance is not None else 0.0, "credit_limit": _v8_amount(_first(raw, "creditLimit")),
        "utilisation_pct": None, "status": status, "default_date": default_date or None,
        "default_balance": default_bal, "monthly_payment": _v8_amount(_first(raw, "regularPaymentAmount", "monthlyPayment", "payment")),
        "payment_history": payment_hist, "last_updated": _fmt_date(_first(raw, "updatedDate", "lastUpdated") or ""),
    }


def _normalise_tu_report(tu_result: dict) -> dict:
    reports = _find_all(tu_result, "report", [])
    report = next((r for r in reports if isinstance(r, dict) and "financialAccountInformation" in r), {})
    pi = report.get("personalInformation", {}) or {}
    client = {
        "name": pi.get("name", ""), "dob": _fmt_date(pi.get("dateOfBirth", "")),
        "address": pi.get("currentAddress", ""), "email": "", "phone": "",
        "matter_ref": tu_result.get("clientReference") or "",
    }
    fai = report.get("financialAccountInformation", {}) or {}
    accounts, defaults = [], []
    for cat, dtype in _TU_CAMEL_CATEGORIES:
        for raw in fai.get(cat, []) or []:
            acc = _tu_account_camel(raw, dtype)
            if not acc:
                continue
            accounts.append(acc)
            if acc["status"] == "DEFAULT":
                defaults.append({"lender": acc["lender"], "status": "DEFAULT",
                                 "amount": acc.get("default_balance") or acc.get("balance") or 0,
                                 "date": acc.get("default_date")})
    # public records
    pub = report.get("publicInformation", {}) or {}
    for j in pub.get("judgments", []) or []:
        defaults.append({"lender": "CCJ", "status": "CCJ",
                         "amount": _v8_amount(_first(j, "amount", "value")) or 0,
                         "date": _fmt_date(_first(j, "date", "judgmentDate") or "")})
    for ins in pub.get("insolvencies", []) or []:
        defaults.append({"lender": "IVA", "status": "INSOLVENCY", "record_type": "Insolvency",
                         "date": _fmt_date(_first(ins, "date", "startDate") or "")})
    return {"client": client, "accounts": accounts, "searches": [], "defaults": defaults,
            "risk_flags": [], "credit_score": None, "_source": "TRANSUNION_REPORT"}


def _merge_report_schemas(a: dict, b: dict) -> dict:
    """Merge two bureau schemas, de-duplicating accounts seen on both bureaus
    (same lender + open date) and keeping the record that carries more evidence."""
    def key(acc):
        return ((acc.get("lender") or "").lower().strip(), acc.get("opened_date") or "")
    merged: dict = {}
    for x in a.get("accounts", []) + b.get("accounts", []):
        k = key(x)
        existing = merged.get(k)
        if existing is None or (x.get("status") == "DEFAULT" and existing.get("status") != "DEFAULT"):
            merged[k] = x
    client = a.get("client") or {}
    if not client.get("name"):
        client = b.get("client") or client
    return {
        "client": client,
        "accounts": list(merged.values()),
        "searches": (a.get("searches") or []) + (b.get("searches") or []),
        "defaults": (a.get("defaults") or []) + (b.get("defaults") or []),
        "risk_flags": (a.get("risk_flags") or []) + (b.get("risk_flags") or []),
        "credit_score": a.get("credit_score") or b.get("credit_score"),
        "_source": "EXPERIAN+TRANSUNION",
    }


def _normalise_bureau_report(data: dict) -> dict:
    results = data.get("results", []) or []
    exp = tu = None
    if _find_all(data, "caisDetails", []):
        try:
            exp = _normalise_experian_report(data)
        except Exception:
            exp = None
    # TransUnion — parse from anywhere in the payload (works for both the combined
    # results[] file and a standalone TransUnion report in the kycResult wrapper).
    if _find_all(data, "financialAccountInformation", []):
        try:
            tu = _normalise_tu_report(data)
        except Exception:
            tu = None
    if exp and tu:
        return _merge_report_schemas(exp, tu)
    if exp or tu:
        return exp or tu
    raise ValueError("Bureau report had no parseable Experian or TransUnion section")


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
