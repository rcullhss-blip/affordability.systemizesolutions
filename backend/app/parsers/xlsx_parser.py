import io
import openpyxl


def extract_xlsx(raw_bytes: bytes) -> str:
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
    parts = []
    for sheet in wb.worksheets:
        parts.append(f"[Sheet: {sheet.title}]")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(c.strip() for c in cells):
                parts.append("\t".join(cells))
    return "\n".join(parts)
