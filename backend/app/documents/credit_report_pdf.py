"""
Consumer Credit Report — professional, UNBRANDED PDF.

Renders the normalised credit report (accounts, defaults/public records, searches)
as a clean bureau-style document. Deliberately carries NO company name or branding
so it can sit in a partner's file on its own. Reuses the rounded-panel styling from
the assessment PDF for a consistent, high-quality look.
"""
import io
from datetime import date, datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether,
)
from reportlab.platypus.frames import Frame
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate

from app.documents.assessment_pdf import RoundedPanel, _S, _ACCT_LABELS

# ── Palette (self-contained, unbranded) ──────────────────────────────────────
# Deep teal-green theme — deliberately distinct from the navy-blue Systemize
# assessment PDF so the two don't look like the same document family.
C_PAGE    = colors.HexColor("#F3F6F5")   # soft warm-neutral page
C_NAVY    = colors.HexColor("#0F3D3A")   # deep teal — cover & header bar
C_SLATE   = colors.HexColor("#115E59")   # teal-800 — table header rows
C_WHITE   = colors.white
C_TEXT    = colors.HexColor("#1E293B")
C_BODY    = colors.HexColor("#475569")
C_MUTED   = colors.HexColor("#94A3B8")
C_DIVIDER = colors.HexColor("#E2E8F0")
C_ROW_ALT = colors.HexColor("#F5F8F7")
C_ACCENT  = colors.HexColor("#5EEAD4")   # light teal — subtitles / accents on dark

_STATUS = {
    "ACTIVE":  ("#166534", "#DCFCE7"),
    "SETTLED": ("#475569", "#F1F5F9"),
    "DEFAULT": ("#991B1B", "#FEE2E2"),
}

PAGE_W, PAGE_H = A4
ML = MR = 1.6 * cm
HEADER_H = 1.3 * cm
FOOTER_H = 0.9 * cm
W = PAGE_W - ML - MR


def _money(v):
    try:
        return "£{:,.0f}".format(float(v)) if v is not None else "—"
    except (TypeError, ValueError):
        return "—"


def _fmt_date(v):
    if not v:
        return "—"
    s = str(v)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return s


def _arrears_summary(ph):
    """Compact worst-status label from a payment_history list."""
    if not ph:
        return "No history"
    codes = [str(c).upper() for c in ph]
    if "D" in codes:
        return "Default"
    nums = [int(c) for c in codes if c.isdigit()]
    worst = max(nums) if nums else 0
    if worst == 0:
        return "Up to date"
    return f"{worst} mo. arrears"


# ── Page decoration (unbranded) ──────────────────────────────────────────────
def _draw_page(canvas, doc):
    canvas.saveState()
    pw, ph = A4
    canvas.setFillColor(C_PAGE)
    canvas.rect(0, 0, pw, ph, fill=1, stroke=0)

    canvas.setFillColor(C_NAVY)
    canvas.rect(0, ph - HEADER_H, pw, HEADER_H, fill=1, stroke=0)
    canvas.setFillColor(C_WHITE)
    canvas.setFont("Helvetica-Bold", 9.5)
    canvas.drawString(ML, ph - HEADER_H + 0.42 * cm, "CREDIT REPORT")
    canvas.setFillColor(C_ACCENT)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(pw - MR, ph - HEADER_H + 0.42 * cm, "Confidential")

    canvas.setFillColor(C_DIVIDER)
    canvas.rect(0, 0, pw, FOOTER_H, fill=1, stroke=0)
    canvas.setFillColor(C_BODY)
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(ML, 0.30 * cm, "Consumer Credit Report  ·  Private & Confidential")
    canvas.drawCentredString(pw / 2, 0.30 * cm, f"Generated: {doc.today}")
    canvas.drawRightString(pw - MR, 0.30 * cm, f"Page {doc.page}")
    canvas.restoreState()


class _ReportDoc(BaseDocTemplate):
    def __init__(self, buf, today, **kw):
        super().__init__(buf, **kw)
        self.today = today
        frame = Frame(ML, FOOTER_H + 0.3 * cm, W,
                      PAGE_H - HEADER_H - FOOTER_H - 0.7 * cm, id="main")
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_draw_page)])


def _section(title):
    return KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=C_DIVIDER, spaceBefore=14, spaceAfter=5),
        Paragraph(title.upper(), _S("sh", fontName="Helvetica-Bold", fontSize=9.5,
                                    textColor=C_NAVY, leading=13, spaceAfter=4)),
    ])


def _stat_cell(value, label):
    return RoundedPanel(
        [Paragraph(str(value), _S("sv", fontName="Helvetica-Bold", fontSize=15,
                                  textColor=C_NAVY, leading=18, alignment=TA_CENTER)),
         Paragraph(label.upper(), _S("sl", fontName="Helvetica", fontSize=6,
                                     textColor=C_MUTED, leading=8, alignment=TA_CENTER))],
        bg=C_WHITE, border=C_DIVIDER, border_width=0.75, radius=8,
        pad_h=6, pad_v=8, gap=2)


def generate_credit_report_pdf(schema: dict) -> bytes:
    buf = io.BytesIO()
    today = date.today().strftime("%d %B %Y")

    client   = schema.get("client") or {}
    accounts = schema.get("accounts") or []
    defaults = [d for d in (schema.get("defaults") or [])]
    searches = schema.get("searches") or []

    name = client.get("name") or "Credit File"
    dob  = _fmt_date(client.get("dob")) if client.get("dob") else "—"
    addr = client.get("address") or "—"

    n_active  = sum(1 for a in accounts if (a.get("status") or "").upper() == "ACTIVE")
    n_default = sum(1 for a in accounts if (a.get("status") or "").upper() == "DEFAULT")
    public_records = [d for d in defaults if str(d.get("status") or "").upper() in ("CCJ", "INSOLVENCY")]

    body_st  = _S("bd", fontName="Helvetica", fontSize=8, textColor=C_BODY, leading=11)
    cell_st  = _S("cl", fontName="Helvetica", fontSize=7.5, textColor=C_TEXT, leading=10)
    cellr_st = _S("cr", fontName="Helvetica", fontSize=7.5, textColor=C_TEXT, leading=10, alignment=TA_RIGHT)
    head_st  = _S("hd", fontName="Helvetica-Bold", fontSize=7, textColor=C_WHITE, leading=9)

    story = []

    # ── Cover ──
    story.append(RoundedPanel(
        [Paragraph(name, _S("nm", fontName="Helvetica-Bold", fontSize=22, textColor=C_WHITE, leading=27)),
         Paragraph("Consumer Credit Report", _S("sub", fontName="Helvetica", fontSize=10,
                                                 textColor=C_ACCENT, leading=14)),
         Spacer(1, 3),
         Paragraph(f'<font color="#94A3B8">Date of birth: {dob}   ·   {addr}   ·   Report date: {today}</font>',
                   _S("mt", fontName="Helvetica", fontSize=7.5, leading=11))],
        bg=C_NAVY, border=None, radius=12, pad_h=20, pad_v=18, gap=5))
    story.append(Spacer(1, 12))

    # ── Summary stats ──
    stats = [_stat_cell(len(accounts), "Accounts"),
             _stat_cell(n_active, "Active"),
             _stat_cell(n_default, "Defaults"),
             _stat_cell(len(public_records), "Public Records"),
             _stat_cell(len(searches), "Searches")]
    t = Table([stats], colWidths=[W / 5.0] * 5)
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(t)

    # ── Accounts ──
    story.append(_section("Credit Accounts"))
    rows = [[Paragraph(h, head_st) for h in
             ["Lender", "Type", "Opened", "Status", "Balance", "Limit", "Conduct"]]]
    for a in accounts:
        st = (a.get("status") or "ACTIVE").upper()
        txt, _bg = _STATUS.get(st, ("#475569", "#F1F5F9"))
        rows.append([
            Paragraph((a.get("lender") or "—")[:34], cell_st),
            Paragraph(_ACCT_LABELS.get((a.get("account_type") or "").upper(), (a.get("account_type") or "—").title()), cell_st),
            Paragraph(_fmt_date(a.get("opened_date")), cell_st),
            Paragraph(f'<font color="{txt}"><b>{st.title()}</b></font>', cell_st),
            Paragraph(_money(a.get("balance")), cellr_st),
            Paragraph(_money(a.get("credit_limit")), cellr_st),
            Paragraph(_arrears_summary(a.get("payment_history")), cell_st),
        ])
    at = Table(rows, colWidths=[W*0.26, W*0.15, W*0.12, W*0.12, W*0.12, W*0.11, W*0.12], repeatRows=1)
    at.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_SLATE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_ROW_ALT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, C_DIVIDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(at)
    if not accounts:
        story.append(Paragraph("No credit accounts on file.", body_st))

    # ── Public records ──
    story.append(_section("Public Records & Defaults"))
    if public_records or n_default:
        pr_rows = [[Paragraph(h, head_st) for h in ["Type", "Lender / Court", "Amount", "Date"]]]
        for d in public_records:
            pr_rows.append([
                Paragraph(str(d.get("record_type") or d.get("status") or "Record").title(), cell_st),
                Paragraph((d.get("lender") or "—")[:36], cell_st),
                Paragraph(_money(d.get("amount")) if d.get("amount") else "—", cellr_st),
                Paragraph(_fmt_date(d.get("date")), cell_st),
            ])
        for a in accounts:
            if (a.get("status") or "").upper() == "DEFAULT":
                pr_rows.append([
                    Paragraph("Default", cell_st),
                    Paragraph((a.get("lender") or "—")[:36], cell_st),
                    Paragraph(_money(a.get("default_balance") or a.get("balance")), cellr_st),
                    Paragraph(_fmt_date(a.get("default_date")), cell_st),
                ])
        prt = Table(pr_rows, colWidths=[W*0.22, W*0.44, W*0.16, W*0.18], repeatRows=1)
        prt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_SLATE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_ROW_ALT]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, C_DIVIDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(prt)
    else:
        story.append(Paragraph("No public records or defaults on file.", body_st))

    # ── Searches ──
    story.append(_section("Credit Searches"))
    if searches:
        s_rows = [[Paragraph(h, head_st) for h in ["Date", "Searched By", "Type"]]]
        for s in searches[:40]:
            s_rows.append([
                Paragraph(_fmt_date(s.get("date")), cell_st),
                Paragraph((s.get("lender") or "—")[:44], cell_st),
                Paragraph((s.get("search_subtype") or s.get("search_type") or "—").title(), cell_st),
            ])
        stbl = Table(s_rows, colWidths=[W*0.18, W*0.56, W*0.26], repeatRows=1)
        stbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_SLATE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_ROW_ALT]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, C_DIVIDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(stbl)
    else:
        story.append(Paragraph("No credit-application searches on file.", body_st))

    _ReportDoc(buf, today, pagesize=A4).build(story)
    return buf.getvalue()
