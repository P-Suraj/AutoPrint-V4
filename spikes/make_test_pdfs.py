"""Phase 1 spike: generate the fixed PDF test set into spikes/_out/pdfs/.

Throwaway code. Not imported by any app.
"""
import os
import random
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "_out" / "pdfs"
OUT.mkdir(parents=True, exist_ok=True)


def text_pdf(name: str, pages: int, mixed: bool = False) -> Path:
    path = OUT / name
    c = canvas.Canvas(str(path), pagesize=A4)
    for i in range(1, pages + 1):
        size = landscape(A4) if (mixed and i % 2 == 0) else A4
        c.setPageSize(size)
        w, h = size
        c.setFont("Helvetica-Bold", 28)
        c.drawString(60, h - 80, f"{name}  page {i} of {pages}")
        c.setFont("Helvetica", 12)
        for line in range(1, 40):
            c.drawString(60, h - 110 - line * 16, f"Line {line}: the quick brown fox jumps over the lazy dog {i}-{line}")
        c.showPage()
    c.save()
    return path


def noisy_image_pdf(name: str, pages: int, px: int) -> Path:
    """Incompressible raster pages, to reach a large file size."""
    from reportlab.lib.utils import ImageReader
    from PIL import Image  # installed as a reportlab dependency

    path = OUT / name
    c = canvas.Canvas(str(path), pagesize=A4)
    rng = random.Random(42)
    for i in range(pages):
        data = bytes(rng.getrandbits(8) for _ in range(px * px * 3))
        img = Image.frombytes("RGB", (px, px), data)
        c.drawImage(ImageReader(img), 20, 100, width=555, height=640)
        c.showPage()
    c.save()
    return path


if __name__ == "__main__":
    made = [
        text_pdf("t01_1page.pdf", 1),
        text_pdf("t02_10pages.pdf", 10),
        text_pdf("t03_50pages.pdf", 50),
        text_pdf("t04_mixed_orientation_6pages.pdf", 6, mixed=True),
        noisy_image_pdf("t05_scan_like_3pages.pdf", 3, 900),
        noisy_image_pdf("t06_large.pdf", 6, 1000),
    ]
    for p in made:
        print(f"{p.name:40s} {os.path.getsize(p)/1024/1024:7.2f} MB")
