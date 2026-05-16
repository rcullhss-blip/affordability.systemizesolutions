import io
import pdfplumber
import pytesseract
from PIL import Image


def extract_pdf(raw_bytes: bytes) -> str:
    text_parts = []

    with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text and page_text.strip():
                text_parts.append(page_text)
            else:
                # Scanned page — OCR fallback
                img = page.to_image(resolution=200).original
                ocr_text = pytesseract.image_to_string(img)
                if ocr_text.strip():
                    text_parts.append(ocr_text)

    return "\n\n".join(text_parts)
