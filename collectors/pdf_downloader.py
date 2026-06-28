from pathlib import Path

import httpx


def download_pdf(url: str, output_dir: Path = Path("data/pdfs")) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rstrip("/").split("/")[-1] or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"

    output_path = output_dir / filename
    with httpx.Client(timeout=60.0) as client:
        response = client.get(url)
        response.raise_for_status()
        output_path.write_bytes(response.content)
    return output_path

