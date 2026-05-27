"""
Affordability Assessment Report — professional light theme.
Light page, navy cover & header, white rounded cards, coloured pill indicators.
True rounded corners via custom Flowables (RoundedPanel, IndicatorPill).
"""
import io
import re
from datetime import date, datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, Flowable, SimpleDocTemplate,
)
from reportlab.platypus.frames import Frame
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate

# ── Palette ──────────────────────────────────────────────────────────────────
C_PAGE      = colors.HexColor("#F1F5F9")   # very light slate page bg
C_NAVY      = colors.HexColor("#0F172A")   # navy — cover, header bar
C_NAVY_MID  = colors.HexColor("#1E293B")   # dark slate — table headers
C_WHITE     = colors.white
C_BLUE      = colors.HexColor("#2563EB")   # accent blue

# Slate text colours
C_TEXT      = colors.HexColor("#1E293B")   # primary text
C_BODY      = colors.HexColor("#475569")   # body text
C_MUTED     = colors.HexColor("#94A3B8")   # muted / meta text
C_DIVIDER   = colors.HexColor("#E2E8F0")   # divider lines

# Traffic-light colours — labels use pre-litigation language, not legal conclusions
TL = {
    "GREEN": {
        "text":  "#15803D",
        "bg":    colors.HexColor("#F0FDF4"),
        "bd":    colors.HexColor("#22C55E"),
        "label": "Strong",
    },
    "AMBER": {
        "text":  "#92400E",
        "bg":    colors.HexColor("#FFFBEB"),
        "bd":    colors.HexColor("#F59E0B"),
        "label": "Borderline",
    },
    "RED": {
        "text":  "#64748B",
        "bg":    colors.HexColor("#F8FAFC"),
        "bd":    colors.HexColor("#CBD5E1"),
        "label": "Weak",
    },
}

# Indicator pill colours
PIL_FOUND_BG  = colors.HexColor("#FFF1F2")
PIL_FOUND_BD  = colors.HexColor("#FCA5A5")
PIL_FOUND_DOT = colors.HexColor("#DC2626")
PIL_FOUND_TXT = colors.HexColor("#991B1B")
PIL_NOT_BG    = colors.HexColor("#F8FAFC")
PIL_NOT_BD    = colors.HexColor("#E2E8F0")
PIL_NOT_DOT   = colors.HexColor("#CBD5E1")
PIL_NOT_TXT   = colors.HexColor("#94A3B8")

PAGE_W, PAGE_H = A4
ML = MR = 1.8 * cm
MT = MB = 1.2 * cm
HEADER_H = 1.4 * cm
FOOTER_H = 0.9 * cm
W = PAGE_W - ML - MR

# ── 9 Affordability indicators ───────────────────────────────────────────────
INDICATORS = [
    ("Active CCJ / Public Record",
     ["active_ccj", "ccj", "multiple_ccj", "multiple_ccjs", "public_record_insolvency", "insolvency"],
     "CCJ or public insolvency record on file — significant indicator of unresolved financial difficulty."),
    ("Multiple CCJs",
     ["multiple_ccj", "ccj_multiple", "multiple_ccjs"],
     "Multiple CCJs or public records present — persistent pattern of serious financial difficulty."),
    ("Active Default",
     ["active_default", "default", "active_adverse", "default_registered", "active_adverse_at_lending"],
     "Adverse entries on file before lending — failure to meet existing credit obligations."),
    ("Debt Collection Account",
     ["debt_collection", "collection_account", "collection"],
     "Account(s) transferred to debt collectors — escalating, unresolved financial difficulty."),
    ("AP Marker (Arrangement to Pay)",
     ["ap_marker", "arrangement_to_pay", "arrangement"],
     "Formal arrangement recorded — applicant could not meet original payment terms."),
    ("Arrears in Last 6 Months",
     ["arrears", "missed_payment", "late_payment", "repeated_missed", "repeated_missed_payments"],
     "Adverse payment markers identified — persistent signs of financial distress."),
    ("Credit Utilisation >80%",
     ["high_utilisation", "utilisation", "elevated_utilisation"],
     "High or excessive utilisation — over-reliance on available credit, insufficient financial headroom."),
    ("Rapid Borrowing / Debt Stacking",
     ["rapid_borrowing", "debt_stacking", "multiple_hard_searches", "hard_searches"],
     "Multiple credit accounts or application footprints in a short window — active financial pressure."),
    ("Repeat Lending",
     ["repeat_lending", "repeat_borrowing"],
     "Same lender continued approving credit despite existing indicators of financial difficulty."),
]

_ACCT_LABELS = {
    "CREDIT_CARD": "Credit Card", "PERSONAL_LOAN": "Personal Loan",
    "PAYDAY_LOAN": "Payday Loan", "HIRE_PURCHASE": "Hire Purchase",
    "OVERDRAFT": "Overdraft", "STORE_CARD": "Store Card",
    "MAIL_ORDER": "Mail Order", "HOME_CREDIT": "Home Credit",
    "MORTGAGE": "Mortgage", "CURRENT_ACCOUNT": "Current Account",
    "TELECOM": "Telecommunications", "UTILITY": "Utility", "OTHER": "Other",
}

# Confidence grade display config
_CONF_COLOURS = {
    "High":   "#15803D",
    "Medium": "#B45309",
    "Low":    "#64748B",
}
# Severity weights for on-the-fly confidence computation in the PDF
_SEV_WEIGHTS = {"CRITICAL": 4, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
_CONF_MAX    = 14


def _fmt_type(val):
    v = (val or "").strip().upper()
    return _ACCT_LABELS.get(v, val.replace("_", " ").title() if val else "—")

def _strip_score(text):
    return re.sub(r'\s*\(Preliminary claim score:\s*\d+(?:\.\d+)?/\d+\)', '', text).strip()

def _fmt_money(val):
    try:
        return f"£{float(val):,.0f}"
    except (TypeError, ValueError):
        return "—"

def _fmt_date(val):
    if not val:
        return "—"
    if isinstance(val, (date, datetime)):
        return val.strftime("%d %b %Y")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%B %Y", "%b %Y"):
        try:
            return datetime.strptime(str(val), fmt).strftime("%d %b %Y")
        except ValueError:
            pass
    return str(val)

def _flag_found(keywords, all_flags):
    flat = " ".join(
        (f.get("flag_type", "") + " " + f.get("type", "") + " " + f.get("description", "")).lower()
        if isinstance(f, dict) else str(f).lower()
        for f in all_flags
    )
    return any(kw.lower() in flat for kw in keywords)

def _confidence_from_flags(flags: list) -> tuple[str, int]:
    """Compute evidence confidence grade from severity-weighted flags."""
    weight = sum(
        _SEV_WEIGHTS.get(f.get("severity", "").upper(), 0)
        for f in flags
        if isinstance(f, dict) and f.get("type", "").upper() != "POSSIBLE_DEBT_PURCHASER"
    )
    pct   = min(round(weight / _CONF_MAX * 100), 100)
    grade = "High" if pct >= 65 else ("Medium" if pct >= 35 else "Low")
    return grade, pct

def _S(name, **kw):
    return ParagraphStyle(name, **kw)


# ── Custom Flowable: RoundedPanel ────────────────────────────────────────────
class RoundedPanel(Flowable):
    """Renders a list of Flowables inside a true rounded-corner panel."""

    def __init__(self, items, bg, border=None, border_width=1.0,
                 radius=10, pad_h=14, pad_v=12, gap=6, width=None):
        Flowable.__init__(self)
        self._items = list(items)
        self._bg    = bg
        self._bd    = border
        self._bw    = border_width
        self._r     = radius
        self._ph    = pad_h
        self._pv    = pad_v
        self._gap   = gap
        self._fw    = width
        self._layout = []
        self._h      = 0
        self._aw     = 0

    def wrap(self, aw, ah):
        self._aw = self._fw or aw
        inner_w  = self._aw - 2 * self._ph

        wrapped  = []
        total_h  = self._pv
        for i, item in enumerate(self._items):
            _, ih = item.wrap(inner_w, 100_000)
            wrapped.append((item, ih))
            total_h += ih
            if i < len(self._items) - 1:
                total_h += self._gap
        total_h += self._pv

        self._layout = []
        y = total_h - self._pv
        for i, (item, ih) in enumerate(wrapped):
            y -= ih
            self._layout.append((item, self._ph, y, ih))
            if i < len(wrapped) - 1:
                y -= self._gap

        self._h = total_h
        return self._aw, self._h

    def split(self, aw, ah):
        # Return [self] so ReportLab moves this panel to the next page rather
        # than trying to break it mid-render. "Splitting error(n==2)" is raised
        # when split() returns 2 items in certain layout contexts; returning
        # [self] avoids that while still allowing page-breaks before the panel.
        return [self]

    def draw(self):
        canv = self.canv
        w, h = self._aw, self._h
        canv.setFillColor(self._bg)
        if self._bd:
            canv.setStrokeColor(self._bd)
            canv.setLineWidth(self._bw)
            canv.roundRect(0, 0, w, h, self._r, fill=1, stroke=1)
        else:
            canv.roundRect(0, 0, w, h, self._r, fill=1, stroke=0)
        for item, x, y, _ in self._layout:
            item.drawOn(canv, x, y)


# ── Custom Flowable: IndicatorPill ────────────────────────────────────────────
class IndicatorPill(Flowable):
    """Full-width pill badge for a single affordability indicator."""
    H   = 40
    GAP = 5

    def __init__(self, label, desc, found, width=None):
        Flowable.__init__(self)
        self._label = label
        self._desc  = desc
        self._found = found
        self._fw    = width

    def wrap(self, aw, ah):
        self._aw = self._fw or aw
        return self._aw, self.H + self.GAP

    def draw(self):
        canv = self.canv
        w = self._aw
        h = self.H
        r = 8

        if self._found:
            bg    = PIL_FOUND_BG
            bd    = PIL_FOUND_BD
            dot_c = PIL_FOUND_DOT
            sts_c = PIL_FOUND_TXT
            sts   = "FOUND"
            lbl_c = PIL_FOUND_TXT
            dsc_c = colors.HexColor("#DC2626")
        else:
            bg    = PIL_NOT_BG
            bd    = PIL_NOT_BD
            dot_c = PIL_NOT_DOT
            sts_c = PIL_NOT_TXT
            sts   = "Not found"
            lbl_c = C_BODY
            dsc_c = PIL_NOT_TXT

        canv.setFillColor(bg)
        canv.setStrokeColor(bd)
        canv.setLineWidth(0.75)
        canv.roundRect(0, self.GAP, w, h, r, fill=1, stroke=1)

        mid_y = self.GAP + h / 2

        # Dot
        canv.setFillColor(dot_c)
        canv.circle(16, mid_y, 5, fill=1, stroke=0)

        # Status
        canv.setFont("Helvetica-Bold", 8)
        canv.setFillColor(sts_c)
        sts_w = canv.stringWidth(sts, "Helvetica-Bold", 8)
        canv.drawString(28, mid_y - 4, sts)

        # Vertical separator
        sep_x = 28 + sts_w + 14
        canv.setStrokeColor(bd)
        canv.setLineWidth(0.5)
        canv.line(sep_x, mid_y - 11, sep_x, mid_y + 11)

        # Label
        canv.setFont("Helvetica-Bold", 9)
        canv.setFillColor(lbl_c)
        lbl_w = canv.stringWidth(self._label, "Helvetica-Bold", 9)
        canv.drawString(sep_x + 12, mid_y - 4.5, self._label)

        # Description (truncated)
        desc_x = sep_x + 12 + lbl_w + 16
        avail  = w - desc_x - 16
        desc   = self._desc
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(dsc_c)
        while desc and canv.stringWidth(desc, "Helvetica", 7.5) > avail:
            desc = desc[:-1]
        if desc != self._desc:
            desc = desc.rstrip() + "…"
        canv.drawString(desc_x, mid_y - 4, desc)


# ── Page template ────────────────────────────────────────────────────────────
def _draw_page(canvas, doc):
    canvas.saveState()
    pw, ph = A4

    # Light page background
    canvas.setFillColor(C_PAGE)
    canvas.rect(0, 0, pw, ph, fill=1, stroke=0)

    # Navy header bar
    canvas.setFillColor(C_NAVY)
    canvas.rect(0, ph - HEADER_H, pw, HEADER_H, fill=1, stroke=0)
    canvas.setFillColor(C_WHITE)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(ML, ph - HEADER_H + 0.44 * cm, "SYSTEMIZE")
    canvas.setFillColor(colors.HexColor("#93C5FD"))
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(ML + 74, ph - HEADER_H + 0.44 * cm, "Affordability Intelligence Platform")

    # Footer
    canvas.setFillColor(C_DIVIDER)
    canvas.rect(0, 0, pw, FOOTER_H, fill=1, stroke=0)
    canvas.setFillColor(C_BODY)
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(ML, 0.30 * cm, "Credit Report Analysis  |  Systemize  |  Pre-Litigation Triage")
    canvas.drawCentredString(pw / 2, 0.30 * cm, f"Generated: {doc.today}")
    canvas.drawRightString(pw - MR, 0.30 * cm, f"Page {doc.page}")
    canvas.restoreState()


class _AssessmentDoc(BaseDocTemplate):
    def __init__(self, buf, today, **kw):
        super().__init__(buf, **kw)
        self.today = today
        frame = Frame(ML, FOOTER_H + 0.3 * cm, W,
                      PAGE_H - HEADER_H - FOOTER_H - 0.7 * cm, id="main")
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_draw_page)])


# ── Style helpers ────────────────────────────────────────────────────────────
def _styles():
    return {
        "h2":   _S("h2",   fontName="Helvetica-Bold", fontSize=9.5, textColor=C_NAVY,
                    leading=13, spaceBefore=6, spaceAfter=4),
        "body": _S("body", fontName="Helvetica", fontSize=8.5, textColor=C_BODY,
                    leading=13, spaceAfter=2),
        "small":_S("sm",   fontName="Helvetica", fontSize=6.5, textColor=C_MUTED, leading=9),
    }

def _divider():
    return HRFlowable(width="100%", thickness=0.5, color=C_DIVIDER,
                      spaceAfter=5, spaceBefore=14)

def _section_header(text, st):
    return KeepTogether([_divider(), Paragraph(text.upper(), st["h2"])])


# ── Cover panel ──────────────────────────────────────────────────────────────
def _cover_panel(client_name, matter_ref, dob, address, today):
    items = [
        Paragraph(client_name,
                  _S("cn", fontName="Helvetica-Bold", fontSize=24,
                     textColor=C_WHITE, leading=30)),
        Paragraph("Affordability Intelligence Report",
                  _S("cs", fontName="Helvetica", fontSize=10,
                     textColor=colors.HexColor("#93C5FD"), leading=14)),
        Spacer(1, 4),
        Paragraph(
            f'<font color="#64748B">Matter: {matter_ref}'
            f'   ·   DOB: {dob}   ·   {address}   ·   {today}</font>',
            _S("cm", fontName="Helvetica", fontSize=7.5, leading=11)),
    ]
    return RoundedPanel(items, bg=C_NAVY, border=None, radius=12,
                        pad_h=20, pad_v=18, gap=5)


# ── Overall traffic-light badge ──────────────────────────────────────────────
def _tl_badge(tl):
    tl  = str(tl).upper()
    cfg = TL.get(tl, TL["RED"])
    p   = Paragraph(
        f'<font color="{cfg["text"]}"><b>{cfg["label"]}</b></font>',
        _S("badge", fontName="Helvetica-Bold", fontSize=14, leading=18,
           alignment=TA_CENTER),
    )
    return RoundedPanel([p], bg=cfg["bg"], border=cfg["bd"], border_width=1.5,
                        radius=10, pad_h=20, pad_v=14)


# ── Stats bar ────────────────────────────────────────────────────────────────
def _stats_bar(active_accs, adverse_n, app_searches_n, in_scope_n, locs_n):
    stats = [
        (str(active_accs),    "Active Facilities",   "#64748B"),
        (str(adverse_n),      "Adverse Records",     "#DC2626"),
        (str(app_searches_n), "Application Searches","#64748B"),
        (str(in_scope_n),     "Potential Claims",    "#92400E"),
        (str(locs_n),         "LOCs Generated",      "#15803D"),
    ]
    inner_w = W - 20
    col_w   = inner_w / 5
    top_row, bot_row = [], []
    for num, label, clr in stats:
        top_row.append(Paragraph(
            f'<font color="{clr}"><b>{num}</b></font>',
            _S(f"sn{num}", fontName="Helvetica-Bold", fontSize=22,
               leading=26, alignment=TA_CENTER)))
        bot_row.append(Paragraph(
            label,
            _S(f"sl{label}", fontName="Helvetica", fontSize=7,
               textColor=C_MUTED, leading=10, alignment=TA_CENTER)))

    t = Table([top_row, bot_row], colWidths=[col_w] * 5)
    t.setStyle(TableStyle([
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("LINEAFTER",     (0, 0), (-2, -1), 0.5, C_DIVIDER),
    ]))
    return RoundedPanel([t], bg=C_WHITE, border=C_DIVIDER, border_width=0.75,
                        radius=10, pad_h=10, pad_v=14, gap=0)


# ── Indicator pills ──────────────────────────────────────────────────────────
def _indicator_ladder(all_flags):
    return [IndicatorPill(label, desc, _flag_found(keywords, all_flags))
            for label, keywords, desc in INDICATORS]


# ── Lender card ──────────────────────────────────────────────────────────────
def _narrative(lender, flags, acc, cal):
    parts = []
    opened_str = _fmt_date(acc.get("opened_date"))

    if cal and cal.get("lending_date"):
        defs    = cal.get("active_defaults_count", 0) or 0
        missed  = cal.get("missed_payments_6m_prior", 0) or 0
        total_d = cal.get("total_debt", 0) or 0
        n_accs  = cal.get("active_account_count", 0) or 0

        if defs > 0:
            def_list = cal.get("active_defaults_list", [])
            names = ", ".join(d.get("lender", "") for d in def_list[:2] if d.get("lender"))
            parts.append(
                f"At the time {lender} approved this credit on {opened_str}, the credit file "
                f"recorded <b>{defs} adverse {'entry' if defs == 1 else 'entries'}</b>"
                + (f" (including {names})" if names else "")
                + " — indicating existing financial difficulty at date of lending."
            )
        if missed > 0:
            if missed >= 5:
                parts.append(
                    "<b>Persistent adverse repayment conduct</b> identified across active accounts — "
                    "multiple arrears markers present on the credit file."
                )
            else:
                parts.append(
                    "<b>Adverse payment markers</b> identified on active accounts at time of lending — "
                    "ongoing signs of financial distress."
                )
        if total_d > 0 and n_accs > 0:
            parts.append(
                f"Total outstanding exposure at date of lending: "
                f"<b>{_fmt_money(total_d)}</b> across {n_accs} active credit facilities."
            )
    else:
        for f in flags:
            if isinstance(f, dict) and f.get("severity") in ("CRITICAL", "HIGH"):
                d = _strip_score(f.get("description", ""))
                if d and f.get("type") != "POSSIBLE_DEBT_PURCHASER":
                    parts.append(d + ".")
                    break
        if not parts:
            for f in flags:
                if isinstance(f, dict):
                    d = _strip_score(f.get("description", ""))
                    if d and f.get("type") != "POSSIBLE_DEBT_PURCHASER":
                        parts.append(d + ".")
                        break

    return " ".join(parts) or "Preliminary affordability indicators identified at date of lending."


def _lender_card(result, accounts):
    tl      = str(getattr(result, "traffic_light", "RED") or "RED").upper()
    lender  = getattr(result, "lender_name", None) or "Unknown"
    flags   = getattr(result, "risk_flags",   None) or []
    loc_gen = bool(getattr(result, "loc_generated", False))

    cfg = TL.get(tl, TL["RED"])
    acc = next((a for a in accounts
                if (a.get("lender", "") or "").lower() == lender.lower()), {})
    cal = acc.get("computed_at_lending") or {}

    is_debt_purchaser = any(
        isinstance(f, dict) and f.get("type") == "POSSIBLE_DEBT_PURCHASER"
        for f in flags
    )

    loc_clr = "#15803D" if loc_gen else "#92400E"
    loc_lbl = "✓ LOC Generated" if loc_gen else "Referred for Legal Review"

    grade, conf_pct = _confidence_from_flags(flags)
    conf_clr = _CONF_COLOURS.get(grade, "#64748B")

    sev_map = {
        "CRITICAL": "#DC2626", "HIGH": "#EA580C",
        "MEDIUM":   "#B45309", "LOW":  "#64748B",
    }

    items = []

    # Debt purchaser warning banner
    if is_debt_purchaser:
        items.append(Paragraph(
            '<font color="#92400E"><b>⚠ Manual Review Required</b></font>'
            '<font color="#B45309"> — possible debt purchaser; verify originating lender before issuing LOC</font>',
            _S("dpw", fontName="Helvetica", fontSize=7.5, leading=11,
               backColor=colors.HexColor("#FFFBEB")),
        ))

    # Lender name + TL inline
    items.append(Paragraph(
        f'<font color="#0F172A"><b>{lender}</b></font>'
        f'&nbsp;&nbsp;&nbsp;'
        f'<font color="{cfg["text"]}"><b>{cfg["label"]}</b></font>',
        _S("lh", fontName="Helvetica-Bold", fontSize=11,
           textColor=C_TEXT, leading=16),
    ))

    # Meta row — type, opened, status, LOC status, confidence
    items.append(Paragraph(
        f'<font color="#94A3B8">'
        f'{_fmt_type(acc.get("account_type",""))}  ·  '
        f'Opened: {_fmt_date(acc.get("opened_date"))}  ·  '
        f'Status: {acc.get("status","—")}  ·  '
        f'</font>'
        f'<font color="{loc_clr}"><b>{loc_lbl}</b></font>'
        f'<font color="#94A3B8">  ·  Evidence Strength: </font>'
        f'<font color="{conf_clr}"><b>{grade}</b></font>',
        _S("meta", fontName="Helvetica", fontSize=7.5, leading=11),
    ))

    # Narrative
    items.append(Paragraph(
        _narrative(lender, flags, acc, cal),
        _S("narr", fontName="Helvetica", fontSize=8.5,
           textColor=C_BODY, leading=13),
    ))

    # Flag lines (skip debt purchaser — already shown as banner)
    for f in flags:
        if isinstance(f, dict):
            if f.get("type") == "POSSIBLE_DEBT_PURCHASER":
                continue
            sev  = f.get("severity", "").upper()
            dtxt = _strip_score(f.get("description", ""))
            sclr = sev_map.get(sev, "#64748B")
            if dtxt:
                items.append(Paragraph(
                    f'<font color="{sclr}"><b>[{sev}]</b></font> '
                    f'<font color="#64748B">{dtxt}</font>',
                    _S(f"fl{sev}", fontName="Helvetica", fontSize=7.5, leading=11),
                ))

    return RoundedPanel(items, bg=C_WHITE, border=cfg["bd"], border_width=1.5,
                        radius=10, pad_h=14, pad_v=12, gap=7)


# ── All accounts table ────────────────────────────────────────────────────────
def _accounts_table(accounts, lender_results):
    hdr_s = _S("th",  fontName="Helvetica-Bold", fontSize=7.5,
                textColor=C_WHITE, leading=10)
    hdr_r = _S("thr", fontName="Helvetica-Bold", fontSize=7.5,
                textColor=C_WHITE, leading=10, alignment=TA_RIGHT)
    header = [
        Paragraph("<b>Lender</b>",  hdr_s),
        Paragraph("<b>Type</b>",    hdr_s),
        Paragraph("<b>Opened</b>",  hdr_s),
        Paragraph("<b>Closed</b>",  hdr_s),
        Paragraph("<b>Balance</b>", hdr_r),
        Paragraph("<b>Status</b>",  hdr_s),
    ]
    col_w = [W * 0.26, W * 0.17, W * 0.13, W * 0.13, W * 0.13, W * 0.18]

    def cell(txt, right=False):
        return Paragraph(str(txt) if txt else "—",
                         _S("ac", fontName="Helvetica", fontSize=7.5,
                            textColor=C_BODY, leading=10,
                            alignment=(TA_RIGHT if right else TA_LEFT)))

    def _sort_key(a):
        status = (a.get("status") or "").upper()
        order  = {"ACTIVE": 0, "DEFAULT": 1, "DEFAULTED": 1, "SETTLED": 2}
        return (order.get(status, 3), -(len(a.get("opened_date") or "")))

    rows = [header]
    for acc in sorted(accounts, key=_sort_key):
        rows.append([
            cell(acc.get("lender", "—")),
            cell(_fmt_type(acc.get("account_type", ""))),
            cell(_fmt_date(acc.get("opened_date"))),
            cell(_fmt_date(acc.get("settled_date") or acc.get("closed_date"))),
            cell(_fmt_money(acc.get("balance") or acc.get("current_balance")), right=True),
            cell(acc.get("status", "—")),
        ])

    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  C_NAVY_MID),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, colors.HexColor("#F8FAFC")]),
        ("BOX",           (0, 0), (-1, -1), 0.75, C_DIVIDER),
        ("LINEBELOW",     (0, 0), (-1, 0),  1.0,  C_DIVIDER),
        ("INNERGRID",     (0, 1), (-1, -1), 0.3,  C_DIVIDER),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        # ROUNDEDCORNERS omitted — unreliable with ROWBACKGROUNDS; table splits across pages
    ]))
    return t


# ── Out-of-scope panel ────────────────────────────────────────────────────────
def _out_of_scope_panel(results, accounts):
    if not results:
        return RoundedPanel(
            [Paragraph(
                '<font color="#94A3B8">All assessed lenders were identified as having potential '
                'affordability indicators. No lenders fall outside scope for this file.</font>',
                _S("oos0", fontName="Helvetica", fontSize=8.5, leading=13),
            )],
            bg=C_WHITE, border=C_DIVIDER, border_width=0.75, radius=10,
            pad_h=14, pad_v=14,
        )

    items = []
    for i, r in enumerate(results):
        lender   = getattr(r, "lender_name", None) or "Unknown"
        flags    = getattr(r, "risk_flags",   None) or []
        acc      = next((a for a in accounts
                         if (a.get("lender", "") or "").lower() == lender.lower()), {})
        acc_type = _fmt_type(acc.get("account_type", ""))
        opened   = _fmt_date(acc.get("opened_date"))

        reason = "Insufficient preliminary indicators to support a potential claim at this stage."
        for f in flags:
            if isinstance(f, dict) and f.get("type") != "POSSIBLE_DEBT_PURCHASER":
                d = _strip_score(f.get("description", ""))
                if d:
                    reason = d
                    break

        items.append(Paragraph(
            f'<font color="#1E293B"><b>{lender}</b></font>'
            f'<font color="#94A3B8">  ·  {acc_type}  ·  {opened}</font>',
            _S("oos_h", fontName="Helvetica-Bold", fontSize=8.5, leading=12),
        ))
        items.append(Paragraph(
            f'<font color="#94A3B8">{reason}</font>',
            _S("oos_b", fontName="Helvetica", fontSize=7.5, leading=11),
        ))
        if i < len(results) - 1:
            items.append(HRFlowable(width="100%", thickness=0.3, color=C_DIVIDER,
                                    spaceAfter=2, spaceBefore=2))

    return RoundedPanel(items, bg=C_WHITE, border=C_DIVIDER, border_width=0.75,
                        radius=10, pad_h=14, pad_v=14, gap=4)


# ── Main generator ────────────────────────────────────────────────────────────
def generate_assessment_pdf(schema: dict, lender_results) -> bytes:
    buf   = io.BytesIO()
    today = date.today().strftime("%d %B %Y")

    client      = schema.get("client", {})
    client_name = client.get("name") or "Unknown Client"
    matter_ref  = client.get("matter_ref") or "—"
    dob         = _fmt_date(client.get("dob")) if client.get("dob") else "—"
    address     = client.get("address") or "—"

    accounts = schema.get("accounts", [])
    defaults = schema.get("defaults", [])
    searches = schema.get("searches", [])

    results   = list(lender_results)
    all_flags = []
    for r in results:
        rf = getattr(r, "risk_flags", None) or []
        all_flags.extend(rf)
    if defaults:
        all_flags.append({"type": "active_default", "description": "default registered"})

    def _tl(r):
        return str(getattr(r, "traffic_light", "RED") or "RED").upper()

    lights    = [_tl(r) for r in results]
    overall   = "GREEN" if "GREEN" in lights else ("AMBER" if "AMBER" in lights else "RED")
    in_scope  = [r for r in results if _tl(r) in ("GREEN", "AMBER")]
    out_scope = [r for r in results if _tl(r) == "RED"]
    locs_count = sum(1 for r in results if getattr(r, "loc_generated", False))

    # Active facilities vs total tradelines
    active_accs = sum(1 for a in accounts if (a.get("status") or "").upper() == "ACTIVE")
    total_accs  = len(accounts)

    # Confirmed credit application searches only (not quotation/identity/management)
    app_searches = [
        s for s in searches
        if (s.get("search_type", "") or "").upper() == "HARD"
        and s.get("search_subtype", None) in {None, "APPLICATION"}
    ]

    st = _styles()

    doc = _AssessmentDoc(
        buf, today,
        pagesize=A4,
        leftMargin=ML, rightMargin=MR,
        topMargin=MT + HEADER_H,
        bottomMargin=MB + FOOTER_H,
    )

    story = []

    # Cover
    story.append(_cover_panel(client_name, matter_ref, dob, address, today))
    story.append(Spacer(1, 10))

    # Overall TL badge
    story.append(_tl_badge(overall))
    story.append(Spacer(1, 10))

    # Stats bar
    story.append(_stats_bar(active_accs, len(defaults), len(app_searches), len(in_scope), locs_count))
    story.append(Spacer(1, 14))

    # 9 Indicator pills
    story.append(_section_header("Credit File Indicators", st))
    story.append(Paragraph(
        "Nine standard affordability criteria assessed against the credit file. "
        "Red pills — preliminary indicator identified. Grey pills — not present on file.",
        st["body"],
    ))
    story.append(Spacer(1, 8))
    story.extend(_indicator_ladder(all_flags))
    story.append(Spacer(1, 10))

    # In-scope lenders
    story.append(_section_header(
        f"In-Scope: Potential Claims — {len(in_scope)} Lender{'s' if len(in_scope) != 1 else ''}",
        st,
    ))
    if in_scope:
        story.append(Paragraph(
            "Preliminary indicators support potential affordability claims. "
            "Letters of Claim generated for each lender marked LOC Generated. "
            "Lenders flagged for Manual Review should be verified by the supervising solicitor before LOC is issued.",
            st["body"],
        ))
        story.append(Spacer(1, 10))
        for r in in_scope:
            story.append(_lender_card(r, accounts))
            story.append(Spacer(1, 10))
    else:
        story.append(Paragraph(
            "No lenders reached the preliminary threshold for a potential affordability claim.",
            st["body"],
        ))
    story.append(Spacer(1, 4))

    # Out-of-scope (always shown)
    story.append(_section_header(
        f"Out-of-Scope: Not Pursued — {len(out_scope)} Lender{'s' if len(out_scope) != 1 else ''}",
        st,
    ))
    story.append(Paragraph(
        "Assessed but without sufficient preliminary indicators to support a potential claim at this time.",
        st["body"],
    ))
    story.append(Spacer(1, 8))
    story.append(_out_of_scope_panel(out_scope, accounts))
    story.append(Spacer(1, 14))

    # All accounts table
    if accounts:
        story.append(_section_header("All Credit Accounts on File", st))
        story.append(Paragraph(
            f"Full credit history: {total_accs} tradelines identified — "
            f"{active_accs} active {'facility' if active_accs == 1 else 'facilities'}, "
            f"{total_accs - active_accs} historical/closed. "
            f"Active accounts shown first.",
            st["body"],
        ))
        story.append(Spacer(1, 8))
        story.append(_accounts_table(accounts, results))
        story.append(Spacer(1, 14))

    # Disclaimer
    story.append(_divider())
    story.append(Paragraph(
        "<b>METHODOLOGY &amp; DISCLAIMER</b> — Produced by the Systemize Affordability Intelligence "
        "Platform. All findings represent preliminary risk indicators derived directly from credit "
        "file data for pre-litigation triage purposes. AI has not influenced any scoring or claim "
        "viability determination. Evidence confidence grades reflect the legal persuasiveness of "
        "identified factors. This report does not constitute legal advice or a determination of "
        "lender liability and must be reviewed by a qualified solicitor before any claim is pursued.",
        st["small"],
    ))

    try:
        doc.build(story)
    except Exception:
        # Fallback: plain paragraphs via SimpleDocTemplate — avoids all RoundedPanel
        # layout issues on reports with unusually large content.
        try:
            buf2 = io.BytesIO()
            doc2 = SimpleDocTemplate(
                buf2, pagesize=A4,
                leftMargin=ML, rightMargin=MR,
                topMargin=MT + HEADER_H, bottomMargin=MB + FOOTER_H,
            )
            plain = _S("fb", fontName="Helvetica", fontSize=9, leading=14)
            bold  = _S("fbb", fontName="Helvetica-Bold", fontSize=10, leading=14)
            fallback = [
                Paragraph(f"<b>Affordability Assessment — {client_name}</b>", bold),
                Paragraph(f"Matter ref: {matter_ref}  |  DOB: {dob}  |  {today}", plain),
                Spacer(1, 10),
                Paragraph(f"Overall: <b>{overall}</b>  |  In-scope lenders: {len(in_scope)}  |  LOCs: {locs_count}", plain),
                Spacer(1, 10),
            ]
            for r in in_scope:
                ldr = getattr(r, "lender_name", "Unknown")
                tl  = getattr(r, "traffic_light", "RED")
                fallback.append(Paragraph(f"<b>{ldr}</b> — {tl}", bold))
                for f in (getattr(r, "risk_flags", None) or []):
                    if isinstance(f, dict):
                        d = _strip_score(f.get("description", ""))
                        if d:
                            fallback.append(Paragraph(f"• {d}", plain))
                fallback.append(Spacer(1, 6))
            for r in out_scope:
                ldr = getattr(r, "lender_name", "Unknown")
                fallback.append(Paragraph(f"<b>{ldr}</b> — Insufficient evidence", plain))
            doc2.build(fallback)
            return buf2.getvalue()
        except Exception:
            # Last resort: minimal single-page PDF with just the header line.
            buf3 = io.BytesIO()
            doc3 = SimpleDocTemplate(buf3, pagesize=A4)
            plain = _S("fb2", fontName="Helvetica", fontSize=9, leading=14)
            doc3.build([Paragraph(
                f"Affordability Assessment — {client_name} | {matter_ref} | Overall: {overall}",
                plain,
            )])
            return buf3.getvalue()
    return buf.getvalue()
