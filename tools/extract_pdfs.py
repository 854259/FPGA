from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "01_sources" / "pdf"
TEXT_DIR = ROOT / "02_extracted" / "pdf_text"
METADATA_PATH = ROOT / "02_extracted" / "metadata" / "pdf_metadata.json"

URL_RE = re.compile(r"https?://[^\s<>\]\[）)]+", re.IGNORECASE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_url(url: str) -> str:
    url = re.split(r"[（(]", url, maxsplit=1)[0]
    return url.rstrip(".,;:，。；：'\"")


def extract_pdf(path: Path) -> dict[str, object]:
    reader = PdfReader(path)
    page_texts: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").replace("\x00", "")
        page_texts.append(f"===== PDF_PAGE {page_number} =====\n{text.strip()}\n")

    full_text = "\n".join(page_texts)
    output_path = TEXT_DIR / f"{path.stem}.txt"
    output_path.write_text(full_text, encoding="utf-8", newline="\n")

    urls = sorted({clean_url(url) for url in URL_RE.findall(full_text)})
    metadata = reader.metadata or {}
    return {
        "file": path.name,
        "source_relative_path": path.relative_to(ROOT).as_posix(),
        "text_relative_path": output_path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "pages": len(reader.pages),
        "extracted_characters": len(full_text),
        "extraction_method": "pypdf.PdfReader.page.extract_text",
        "urls": urls,
        "pdf_metadata": {str(key): str(value) for key, value in metadata.items()},
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = [extract_pdf(path) for path in sorted(PDF_DIR.glob("*.pdf"))]
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "records": records,
    }
    METADATA_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
