"""Format detection and routing to the correct parser."""

import json as _json

# Sentinel prefix written into raw_text when the payload is a JSON partner-post.
# The normaliser detects this and bypasses the text-based BoshhhFintech parser.
_JSON_PARTNER_POST_PREFIX = "__JSON_PARTNER_POST__:"


def route_to_parser(filename: str, raw_bytes: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # ── JSON partner-post (Equifax / TransUnion bureau feeds) ─────────────────
    if ext == "json" or _looks_like_json_partner_post(raw_bytes):
        try:
            data = _json.loads(raw_bytes)
            # Re-serialise as a tagged string so normalise_to_schema can detect it
            return _JSON_PARTNER_POST_PREFIX + _json.dumps(data)
        except Exception:
            pass  # fall through to text decode

    if ext == "pdf":
        from app.parsers.pdf_parser import extract_pdf
        return extract_pdf(raw_bytes)

    if ext in ("html", "htm"):
        from app.parsers.html_parser import extract_html
        return extract_html(raw_bytes)

    if ext in ("xlsx", "xls"):
        from app.parsers.xlsx_parser import extract_xlsx
        return extract_xlsx(raw_bytes)

    if ext == "csv":
        return raw_bytes.decode("utf-8", errors="replace")

    if ext == "docx":
        from app.parsers.docx_parser import extract_docx
        return extract_docx(raw_bytes)

    # Fallback: try PDF then HTML
    try:
        from app.parsers.pdf_parser import extract_pdf
        return extract_pdf(raw_bytes)
    except Exception:
        pass

    return raw_bytes.decode("utf-8", errors="replace")


def _looks_like_json_partner_post(raw_bytes: bytes) -> bool:
    """
    Heuristic: does this look like an Equifax or TransUnion partner-post JSON?
    Avoids mistaking CSV/HTML/PDF for JSON.
    """
    try:
        snippet = raw_bytes[:512].decode("utf-8", errors="replace").strip()
        if not snippet.startswith("{"):
            return False
        # Must contain at least one known bureau field
        return any(
            marker in snippet
            for marker in (
                '"clientRefId"',
                '"memberStatus"',
                '"FinancialAccountInformation"',
                '"soleSearch"',
                '"nonAddressSpecificData"',
                '"agency"',
            )
        )
    except Exception:
        return False
