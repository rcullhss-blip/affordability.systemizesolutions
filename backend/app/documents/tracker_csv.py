"""
Proclaim-ready tracker CSV — the single source of truth for the tracker's
column layout and row formatting.

Used by BOTH:
  * the batch export endpoint    (app.api.routes.batches.export_tracker_csv), and
  * the per-case outcome postback (app.workers.irl_outcome), which attaches a
    per-case tracker in this exact format for single (non-batch) cases.

One row per generated LOC (defendant). A case with no viable LOC still emits a
single summary row so the client always appears in the tracker.

Keep the column list here and import it from both call sites — never re-declare
the columns inline — so Ryan's Proclaim import always sees an identical layout
regardless of whether the tracker came from a batch export or a single case.
"""
import csv
import datetime as _dt
import io
import re

_TITLES = {"MR", "MRS", "MS", "MISS", "DR", "PROF", "SIR", "REV", "MASTER"}
_UK_POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)

# Internal traffic light -> the tracker's "Analysis Status" label.
TL_LABELS = {
    "GREEN": "Strong",
    "AMBER": "Borderline",
    "RED":   "Weak",
}

# The exact column order Proclaim expects. Do not reorder or rename.
TRACKER_HEADER = [
    "Client Reference",
    "Timestamp", "Title", "First Name", "Surname", "Date of Birth", "Email", "Phone",
    "Residence 1", "Residence 2", "Residence 3", "Postal Code",
    "Defendant", "Analysis Status", "Case Status",
    "Credit Report", "Assessment PDF", "Letter of Claim",
]

# Firms whose middleware reads a LEADING "Case Key" column as a case-type code.
# Ryans' Proclaim middleware files the case by this code, so every Ryans row
# gets "IL" (Irresponsible Lending) in a "Case Key" column prepended ahead of
# "Client Reference". The Client Reference column then carries OUR per-case
# reference (lead reference), which Ryans store and echo back on the case-
# creation email so we can reconcile. Firms NOT listed here get no Case Key
# column and the original TRACKER_HEADER layout is unchanged (so live First
# Legal / Barings / Accord imports are untouched).
FIRM_CASE_KEY = {
    "ryans": "IL",
}


def case_key_for(firm):
    """The leading 'Case Key' code for a firm, or None if the firm's tracker has
    no Case Key column (i.e. the original layout)."""
    return FIRM_CASE_KEY.get((firm or "").strip().lower())


def tracker_header_for(firm):
    """TRACKER_HEADER, prefixed with a 'Case Key' column for firms whose
    middleware reads it (e.g. Ryans); otherwise the original header."""
    return (["Case Key", *TRACKER_HEADER] if case_key_for(firm)
            else list(TRACKER_HEADER))


def prepend_case_key(rows, firm):
    """Prefix each row with the firm's Case Key cell when the firm uses one;
    otherwise return the rows unchanged (as new lists)."""
    ck = case_key_for(firm)
    return [[ck, *r] for r in rows] if ck else [list(r) for r in rows]


# Firms whose middleware expects dates in UK DD/MM/YYYY format rather than the
# ISO YYYY-MM-DD our pipeline stores. Ryans' Proclaim import needs DD/MM/YYYY.
FIRM_UK_DATES = {"ryans"}


def format_dob(value, firm):
    """Render a date of birth for a firm's tracker. Firms in FIRM_UK_DATES
    (e.g. Ryans) get DD/MM/YYYY; all others keep the value unchanged (ISO).
    An unparseable value is returned untouched so we never drop a DoB."""
    if (firm or "").strip().lower() not in FIRM_UK_DATES:
        return value or ""
    if not value:
        return ""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.strftime("%d/%m/%Y")
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return _dt.datetime.strptime(s[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s  # unparseable — leave as-is rather than lose the value


def split_name(full_name: str):
    """Return (title, first_name, surname) from a full name string."""
    parts = (full_name or "").strip().title().split()
    if not parts:
        return "", "", ""
    if parts[0].upper() in _TITLES:
        return parts[0], (parts[1] if len(parts) > 1 else ""), " ".join(parts[2:])
    return "", parts[0], " ".join(parts[1:])


def split_address(address: str):
    """Return (res1, res2, res3, postcode) from a comma-joined address string."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    postcode = ""
    for i in range(len(parts) - 1, -1, -1):
        if _UK_POSTCODE.search(parts[i]):
            postcode = parts.pop(i).strip().upper()
            break
    return (
        parts[0] if len(parts) > 0 else "",
        parts[1] if len(parts) > 1 else "",
        parts[2] if len(parts) > 2 else "",
        postcode,
    )


def tracker_row(*, client_reference="", timestamp="", name="", dob="", email="",
                phone="", address="", defendant="", traffic_light="",
                case_status="", credit_report_url="", assessment_url="",
                loc_url=""):
    """Build one tracker row (list of cells) in TRACKER_HEADER order."""
    title, first_name, surname = split_name(name)
    res1, res2, res3, postcode = split_address(address)
    return [
        client_reference or "",
        timestamp or "", title, first_name, surname, dob or "", email or "", phone or "",
        res1, res2, res3, postcode,
        defendant or "", TL_LABELS.get((traffic_light or "").upper(), ""), case_status or "",
        credit_report_url or "", assessment_url or "", loc_url or "",
    ]


def rows_to_csv_bytes(rows, header=None) -> bytes:
    """Header + rows -> UTF-8 CSV bytes (matches the streamed batch export).

    Pass `header` (e.g. from tracker_header_for(firm)) when the rows carry a
    firm-specific layout such as Ryans' leading Case Key column; defaults to the
    standard TRACKER_HEADER."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header or TRACKER_HEADER)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def build_case_tracker_rows(*, client_reference, timestamp, name, dob, email,
                            phone, address, lenders, is_blocked,
                            credit_report_url, assessment_url, loc_url_for):
    """
    Rows for a single case — one per generated LOC, mirroring the batch export.

    lenders:      iterable of (lender_name, traffic_light, loc_generated, s3_loc_key)
    is_blocked:   callable(lender_name) -> bool  (lender no longer trading)
    loc_url_for:  callable(s3_loc_key) -> str    (signed URL for a LOC)
    """
    common = dict(
        client_reference=client_reference, timestamp=timestamp, name=name,
        dob=dob, email=email, phone=phone, address=address,
        credit_report_url=credit_report_url, assessment_url=assessment_url,
    )
    lenders = list(lenders)
    locs = [(l, tl, k) for (l, tl, g, k) in lenders if g and k]
    if locs:
        return [
            tracker_row(**common, defendant=lender, traffic_light=tl,
                        case_status="LOC Generated", loc_url=loc_url_for(k))
            for lender, tl, k in locs
        ]
    # No viable LOC — still emit one summary row so the client appears.
    all_blocked = bool(lenders) and all(is_blocked(l) for (l, _, _, _) in lenders)
    case_status = "No Viable Defendant" if all_blocked else "No Viable Claim"
    return [tracker_row(**common, defendant="", traffic_light="",
                        case_status=case_status, loc_url="")]
