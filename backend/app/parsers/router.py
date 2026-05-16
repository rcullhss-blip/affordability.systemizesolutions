"""Format detection and routing to the correct parser."""


def route_to_parser(filename: str, raw_bytes: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

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
