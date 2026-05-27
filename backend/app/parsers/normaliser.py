"""
Converts raw extracted text into the standard internal JSON schema.
Supports:
  - BoshhhFintech HTML-exported PDF format
  - Equifax / TransUnion JSON partner-post format (via json_normaliser)
  - Generic fallback
"""
import json as _json
import re
from datetime import date, datetime

# Sentinel set by router.py when raw bytes are a JSON partner-post
_JSON_PARTNER_POST_PREFIX = "__JSON_PARTNER_POST__:"


# ── Format detection ───────────────────────────────────────────────────────
_BOSHHH_MARKER = re.compile(
    r'api\.boshhhfintech\.com|Agreement Start Date|Forecasted End Date|boshhhfintech',
    re.IGNORECASE,
)

_BOSHHH_ACCOUNT_TYPES = [
    "Comms Supply Account",
    "Credit Card",
    "Current Account",
    "Hire Purchase",
    "Secured Loan",
    "Unsecured Loan",
    "Public Utility Account",
    "Basic Bank Account",
    "Mail Order Account",
    "Home Credit Account",
]

_BOSHHH_TYPE_MAP = {
    "credit card":           "CREDIT_CARD",
    "unsecured loan":        "PERSONAL_LOAN",
    "hire purchase":         "HIRE_PURCHASE",
    "secured loan":          "MORTGAGE",
    "current account":       "CURRENT_ACCOUNT",
    "basic bank account":    "CURRENT_ACCOUNT",
    "comms supply account":  "TELECOM",
    "public utility account":"UTILITY",
    "mail order account":    "MAIL_ORDER",
    "home credit account":   "HOME_CREDIT",
}

# Account types that are financially relevant for affordability claims
_FINANCIAL_TYPES = {"CREDIT_CARD", "PERSONAL_LOAN", "HIRE_PURCHASE", "HOME_CREDIT", "MAIL_ORDER"}


def normalise_to_schema(raw_text: str) -> dict:
    # ── JSON partner-post (Equifax / TransUnion) ───────────────────────────
    if raw_text.startswith(_JSON_PARTNER_POST_PREFIX):
        from app.parsers.json_normaliser import normalise_json_payload
        json_str = raw_text[len(_JSON_PARTNER_POST_PREFIX):]
        data = _json.loads(json_str)
        return normalise_json_payload(data)

    # ── BoshhhFintech PDF/HTML ─────────────────────────────────────────────
    if _BOSHHH_MARKER.search(raw_text):
        return _parse_boshhhfintech(raw_text)

    return _parse_generic(raw_text)


# ══════════════════════════════════════════════════════════════════════════
# BoshhhFintech parser
# ══════════════════════════════════════════════════════════════════════════

def _parse_boshhhfintech(text: str) -> dict:
    return {
        "client":     _boshhh_client(text),
        "accounts":   _boshhh_accounts(text),
        "searches":   _boshhh_searches(text),
        "defaults":   _boshhh_defaults(text),
        "risk_flags": [],
    }


def _boshhh_client(text: str) -> dict:
    name = ""
    # Format 1: HTML — name is first non-empty line (e.g. "ALAN ROBSON\nDate issued:")
    first_line = text.strip().split('\n')[0].strip()
    if re.match(r'^[A-Z][A-Z\s\-\']{2,}[A-Z]$', first_line) and len(first_line.split()) >= 2:
        name = first_line
    # Format 2: PDF print header — "5/13/26, 11:35 PM  LOUISE DUTTON Credit File"
    if not name:
        m = re.search(r'(?:AM|PM)\s+([A-Z][A-Z\s\-\']+[A-Z])\s+Credit File', text)
        if m:
            name = m.group(1).strip()
    # Format 3: <title> tag survived extraction
    if not name:
        m = re.search(r'([A-Z][A-Z\s\-\']+[A-Z])\s+Credit File', text)
        if m:
            name = m.group(1).strip()

    # Address: lines between "Supplied Address 1" and next section header
    address = ""
    addr_lines = []
    addr_m = re.search(
        r'Supplied Address 1\s*\n(.*?)(?:Linked Address|Electoral Register|What are linked)',
        text, re.DOTALL
    )
    if addr_m:
        addr_lines = [ln.strip() for ln in addr_m.group(1).strip().split('\n')
                      if ln.strip() and not ln.strip().startswith('What are')]
        address = ', '.join(addr_lines[:5])

    # DOB: not usually present in Boshhh but try anyway
    dob = ""
    dob_m = re.search(r'(?:Date of Birth|DOB)[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})', text, re.I)
    if dob_m:
        dob = dob_m.group(1)

    # Email — may appear in contact/personal details section
    email = ""
    email_m = re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
    if email_m:
        candidate = email_m.group(0)
        # Exclude known non-personal domains in the credit file itself
        if "boshhhfintech" not in candidate and "boshhh" not in candidate:
            email = candidate

    # Phone — UK mobile/landline
    phone = ""
    phone_m = re.search(
        r'(?:Tel|Phone|Mobile|Contact)[:\s]*((?:0|\+44)[0-9\s\-\(\)]{9,14})',
        text, re.I
    )
    if not phone_m:
        phone_m = re.search(r'\b(07\d{9}|0[123456789]\d[\s\-]?\d{3,4}[\s\-]?\d{4})\b', text)
    if phone_m:
        phone = re.sub(r'[\s\-]', '', phone_m.group(1)).strip()

    return {
        "name": name, "dob": dob, "address": address,
        "email": email, "phone": phone, "matter_ref": "",
    }


def _boshhh_accounts(text: str) -> list:
    accounts = []
    header_re = _boshhh_header_re()
    matches = list(header_re.finditer(text))

    for idx, m in enumerate(matches):
        acc_type_raw = m.group(1).strip()
        header_rest  = m.group(2).strip()

        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block     = text[m.start(): block_end]

        lines_after = text[m.end(): m.end() + 300].split('\n')
        lender      = _boshhh_lender(header_rest, lines_after)

        loan_value_raw  = _bfield(block, r'Loan Value\s+£\s*([0-9,]+(?:\.\d{2})?)')
        credit_limit_raw= _bfield(block, r'Credit Limit\s+£\s*([0-9,N/A]+)')
        start_date      = _bfield(block, r'Agreement Start Date\s+(\d{1,2}/\d{1,2}/\d{4})')
        default_date    = _bfield(block, r'Default Date\s+(\d{1,2}/\d{1,2}/\d{4})')
        settled_date    = _bfield(block, r'Settled Date\s+(\d{1,2}/\d{1,2}/\d{4})')

        acc_type = _BOSHHH_TYPE_MAP.get(acc_type_raw.lower(), "OTHER")

        if default_date:
            status = "DEFAULT"
        elif settled_date:
            status = "SETTLED"
        else:
            status = "ACTIVE"

        loan_float  = _to_float(loan_value_raw)
        limit_float = _to_float(credit_limit_raw) if credit_limit_raw and 'N/A' not in credit_limit_raw else 0.0
        util        = round(loan_float / limit_float * 100, 1) if limit_float > 0 else None

        # Extract payment history row codes (0=OK, 1-6=late, D=default, S=settled)
        payment_codes = _boshhh_payment_codes(block)

        accounts.append({
            "lender":          lender,
            "account_type":    acc_type,
            "opened_date":     start_date,
            "balance":         loan_float,
            "credit_limit":    limit_float,
            "utilisation_pct": util,
            "status":          status,
            "default_date":    default_date,
            "settled_date":    settled_date,
            "payment_history": payment_codes,
        })

    return accounts


def _classify_search_subtype(raw: str) -> str:
    """Classify a raw search type code into a canonical subtype."""
    r = raw.lower()
    if "creditapplication" in r:
        return "APPLICATION"
    if "quotation" in r:
        return "QUOTATION"
    if "customermanagement" in r:
        return "MANAGEMENT"
    if r.startswith("id") or "identity" in r or "idverif" in r:
        return "IDENTITY"
    if "trace" in r:
        return "TRACE"
    if "insurance" in r:
        return "INSURANCE"
    if "nosearch" in r:
        return "NO_SEARCH"
    return "UNKNOWN"


def _boshhh_searches(text: str) -> list:
    searches = []
    # Hard searches table: "YYYY-MM-DD COMPANY_NAME searchType False/True"
    hard_m = re.search(
        r'Hard Searches at Supplied Address 1\s*\n.+?\n(.+?)(?:Hard Searches at Linked|Soft Searches|$)',
        text, re.DOTALL
    )
    if hard_m:
        for row in hard_m.group(1).strip().split('\n'):
            row = row.strip()
            if not row or 'No data' in row or 'Date Of Search' in row:
                continue
            m = re.match(
                r'(\d{4}-\d{2}-\d{2})\s+(.+?)\s+(credit\w*|trace\w*|noSearch\w*|insurance\w*|id\w*)\s+(True|False)',
                row, re.I
            )
            if m:
                raw_type = m.group(3)
                searches.append({
                    "date":           m.group(1),
                    "lender":         m.group(2).strip(),
                    "search_type":    "HARD",
                    "search_subtype": _classify_search_subtype(raw_type),
                    "raw_search_type": raw_type,
                })
    return searches


def _boshhh_defaults(text: str) -> list:
    defaults = []

    # CCJs from Section 03 — must be followed by "Court Name" (not "Old Case Number")
    for ccj_m in re.finditer(
        r'County Court Judgement[^\n]*(\d{4}-\d{2}-\d{2})\s*\n'
        r'Court Name\s+[^\n]+\n'
        r'(?:[^\n]+\n){0,4}?Amount\s+(\d+)\s+GBP',
        text, re.IGNORECASE
    ):
        defaults.append({
            "lender": "CCJ",
            "date":   ccj_m.group(1),
            "amount": float(ccj_m.group(2)),
            "status": "CCJ",
        })

    # Public records: Voluntary Liquidation, Insolvency, Bankruptcy
    seen_public_dates = set()
    for pub_m in re.finditer(
        r'(Voluntary Liquidation|Insolvency|Bankruptcy|Administration)\s*(?:Cases?)?\s*(?:from\s+[^\n]*)?\n'
        r'(?:[^\n]*\n){0,12}?(\d{4}-\d{2}-\d{2})',
        text, re.IGNORECASE
    ):
        pub_date = pub_m.group(2)
        if pub_date in seen_public_dates:
            continue
        seen_public_dates.add(pub_date)
        record_type = pub_m.group(1).upper().replace(" ", "_")
        defaults.append({
            "lender":      "PUBLIC_RECORD",
            "date":        pub_date,
            "amount":      0,
            "status":      "INSOLVENCY",
            "record_type": record_type,
        })

    # Account-level defaults
    header_re = _boshhh_header_re()
    matches   = list(header_re.finditer(text))

    for idx, m in enumerate(matches):
        block_end    = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block        = text[m.start(): block_end]
        default_date = _bfield(block, r'Default Date\s+(\d{1,2}/\d{1,2}/\d{4})')
        if not default_date:
            continue

        lines_after  = text[m.end(): m.end() + 300].split('\n')
        lender       = _boshhh_lender(m.group(2).strip(), lines_after)
        settled_date = _bfield(block, r'Settled Date\s+(\d{1,2}/\d{1,2}/\d{4})')
        loan_raw     = _bfield(block, r'Loan Value\s+£\s*([0-9,]+(?:\.\d{2})?)')

        defaults.append({
            "lender": lender,
            "date":   default_date,
            "amount": _to_float(loan_raw),
            "status": "SATISFIED" if settled_date else "ACTIVE",
        })

    return defaults


# ── BoshhhFintech helpers ──────────────────────────────────────────────────

def _boshhh_header_re():
    types_re = '|'.join(re.escape(t) for t in _BOSHHH_ACCOUNT_TYPES)
    return re.compile(rf'({types_re})\s+from\s+([^\n]+)\n', re.IGNORECASE | re.MULTILINE)


def _boshhh_lender(header_rest: str, lines_after: list) -> str:
    """
    Extract clean lender name from the line after 'from '.
    Handles both same-line and multi-line cases.
    """
    # Case 1: "(I)" present on same line → lender = everything before it
    m = re.match(r'(.+?)\s*\(I\)', header_rest)
    if m:
        return _clean_lender(m.group(1))

    # Case 2: no "(I)" on header line — name may wrap to a subsequent line
    base = header_rest.strip()
    for line in lines_after[:5]:
        line = line.strip()
        if not line:
            continue
        if '(I)' in line:
            cont = re.sub(r'\s*\(I\).*$', '', line).strip()
            # Only append if continuation looks like a name (has letters)
            if cont and re.search(r'[A-Za-z]{2,}', cont):
                return _clean_lender(f"{base} {cont}")
            return _clean_lender(base)
        # Skip pure account-number lines (mostly digits/alphanum, no meaningful words)
        if re.match(r'^[\dA-Z\-\s/\.]+$', line) and not re.search(r'[a-z]{3,}', line):
            continue

    return _clean_lender(base)


def _clean_lender(name: str) -> str:
    name = re.sub(r'\s*\(I\).*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\(EUROPE\)\s*(PLC)?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def _bfield(block: str, pattern: str) -> str | None:
    m = re.search(pattern, block, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _boshhh_payment_codes(block: str) -> list:
    """Extract payment status codes (0, 1-6, D, S, U, N) from payment history grid."""
    ph_m = re.search(r'Payment History\s*\n(.+?)(?:\n\n|\Z)', block, re.DOTALL)
    if not ph_m:
        return []
    codes = re.findall(r'\b([0-9]|[DSUN])\b', ph_m.group(1))
    return codes


def _to_float(val: str | None) -> float:
    if not val:
        return 0.0
    try:
        return float(re.sub(r'[£,\s]', '', val))
    except (ValueError, TypeError):
        return 0.0


# ══════════════════════════════════════════════════════════════════════════
# Generic parser (fallback for non-BoshhhFintech formats)
# ══════════════════════════════════════════════════════════════════════════

def _parse_generic(text: str) -> dict:
    return {
        "client":     _extract_client(text),
        "accounts":   _extract_accounts(text),
        "searches":   _extract_searches(text),
        "defaults":   _extract_defaults(text),
        "risk_flags": [],
    }


def _extract_client(text: str) -> dict:
    name = _find_first(text, [
        r"(?im)^name[:\s]+([A-Z][a-zA-Z\-']+ [A-Z][a-zA-Z\-']+(?:[ ][A-Z][a-zA-Z\-']+)?)$",
        r"(?im)^client[:\s]+([A-Z][a-zA-Z\-']+ [A-Z][a-zA-Z\-']+)$",
        r"(?im)^applicant[:\s]+([A-Z][a-zA-Z\-']+ [A-Z][a-zA-Z\-']+)$",
    ])
    dob = _find_first(text, [
        r"(?im)^(?:date of birth|dob)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})$",
    ])
    matter_ref = _find_first(text, [
        r"(?im)^(?:matter reference|matter ref|file ref|reference|case ref)[:\s#]+([A-Z0-9\-\/]+)$",
    ])
    address = _find_first(text, [r"(?im)^address[:\s]+(.{10,100})$"])
    return {
        "name": name or "", "dob": dob or "",
        "address": address or "", "matter_ref": matter_ref or "",
    }


def _extract_accounts(text: str) -> list:
    accounts = []
    lender_pattern = re.compile(r"(?im)^(?:lender|creditor|company)[:\s]+([^\n]{2,80})$")
    for match in lender_pattern.finditer(text):
        block_text = text[match.start(): match.start() + 800]
        balance   = _find_first(block_text, [r"(?im)^balance[:\s£]+([0-9,]+(?:\.\d{2})?)$"])
        limit     = _find_first(block_text, [r"(?im)^(?:credit limit|limit)[:\s£]+([0-9,]+(?:\.\d{2})?)$"])
        status    = _find_first(block_text, [r"(?im)^status[:\s]+([^\n]{2,40})$"])
        opened    = _find_first(block_text, [r"(?im)^(?:opened|start date|date opened)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\w+ \d{4})$"])
        acc_type_raw = _find_first(block_text, [r"(?im)^account type[:\s]+([^\n]{2,40})$"])
        acc_type  = _map_account_type(acc_type_raw) if acc_type_raw else _infer_account_type(block_text)
        bal_f     = _to_float(balance)
        lim_f     = _to_float(limit)
        util      = round(bal_f / lim_f * 100, 1) if lim_f > 0 else None
        accounts.append({
            "lender": match.group(1).strip(), "account_type": acc_type,
            "opened_date": opened, "balance": bal_f, "credit_limit": lim_f,
            "utilisation_pct": util, "status": status, "payment_history": [],
        })
    return accounts


def _extract_searches(text: str) -> list:
    searches = []
    pattern = re.compile(r"(?i)(?:search|enquiry)[:\s]+([^\n]{5,80})")
    date_p  = re.compile(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\w+ \d{4})")
    for match in pattern.finditer(text):
        line = match.group(1)
        d    = date_p.search(line)
        searches.append({
            "date":        d.group(1) if d else "",
            "lender":      line.split(",")[0].strip() if "," in line else line.strip(),
            "search_type": "HARD" if "hard" in line.lower() else "SOFT",
        })
    return searches


def _extract_defaults(text: str) -> list:
    defaults = []
    pattern  = re.compile(r"(?im)^(?:default)[:\s]+([^\n]{5,200})$")
    date_p   = re.compile(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})")
    amount_p = re.compile(r"£?([0-9,]+(?:\.\d{2})?)\b")
    for match in pattern.finditer(text):
        line = match.group(1).strip()
        d    = date_p.search(line)
        if d:
            lender = line[:d.start()].strip().rstrip(",")
        else:
            lender = line.split()[0] if line.split() else ""
        remainder = line[d.end():] if d else line
        remainder = re.sub(r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}", "", remainder)
        amounts   = [float(m.group(1).replace(",", "")) for m in amount_p.finditer(remainder)
                     if float(m.group(1).replace(",", "")) >= 1]
        defaults.append({
            "lender": lender, "date": d.group(1) if d else "",
            "amount": amounts[0] if amounts else 0, "status": "DEFAULT",
        })
    return defaults


def _map_account_type(raw: str) -> str:
    t = raw.lower().strip()
    if any(w in t for w in ["payday", "short term", "short-term"]):  return "PAYDAY_LOAN"
    if "credit card" in t:                                            return "CREDIT_CARD"
    if any(w in t for w in ["personal loan", "unsecured loan"]):      return "PERSONAL_LOAN"
    if "overdraft" in t:                                              return "OVERDRAFT"
    if "mortgage" in t:                                               return "MORTGAGE"
    if any(w in t for w in ["store card", "catalogue", "buy now"]):  return "STORE_CARD"
    if any(w in t for w in ["hire purchase", " hp "]):                return "HIRE_PURCHASE"
    return "OTHER"


def _infer_account_type(text: str) -> str:
    t = text[:150].lower()
    if any(w in t for w in ["payday", "short term"]):     return "PAYDAY_LOAN"
    if "credit card" in t:                                return "CREDIT_CARD"
    if "personal loan" in t or "unsecured loan" in t:     return "PERSONAL_LOAN"
    if "overdraft" in t:                                  return "OVERDRAFT"
    if "mortgage" in t:                                   return "MORTGAGE"
    if "store card" in t or "catalogue" in t:             return "STORE_CARD"
    return "OTHER"


def _find_first(text: str, patterns: list) -> str | None:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None
