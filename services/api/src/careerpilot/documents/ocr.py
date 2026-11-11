"""Optional OCR through the tesseract CLI (no Python OCR dependency). Reports clearly when
tesseract is unavailable instead of silently returning empty text."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def tesseract_path() -> str | None:
    return shutil.which("tesseract")


def is_available() -> bool:
    return tesseract_path() is not None


def _langs() -> str:
    return os.environ.get("CAREERPILOT_OCR_LANGS", "eng")


def ocr_image_file(path: Path, timeout: int = 120) -> str:
    exe = tesseract_path()
    if not exe:
        raise RuntimeError("tesseract not found on PATH")
    proc = subprocess.run([exe, str(path), "stdout", "-l", _langs(), "--psm", "3"],
                          capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError("tesseract failed: " + proc.stderr.decode("utf-8", "replace")[:200])
    return proc.stdout.decode("utf-8", "replace")


def ocr_image_bytes(data: bytes, suffix: str = ".png") -> str:
    with tempfile.TemporaryDirectory(prefix="cp_ocr_") as d:
        p = Path(d) / f"in{suffix}"
        p.write_bytes(data)
        return ocr_image_file(p)


def ocr_pdf_page(page, dpi: int = 300) -> str:  # noqa: ANN001 - fitz.Page
    pix = page.get_pixmap(dpi=dpi)
    return ocr_image_bytes(pix.tobytes("png"))
