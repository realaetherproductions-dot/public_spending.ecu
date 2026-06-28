from pathlib import Path


def extract_text_from_pdf(pdf_path: Path) -> str:
    """OCR hook. Wire this to OCRmyPDF/Tesseract when scanned PDFs enter the MVP."""
    raise NotImplementedError(f"OCR is not configured yet for {pdf_path}")

