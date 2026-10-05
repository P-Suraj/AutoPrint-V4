"""Test PDF builders. No external files: every case is generated, so the suite is self-contained."""
import io
import os
import random

from pypdf import PdfWriter


def blank(pages: int = 1) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def encrypted(pages: int = 1) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    w.encrypt("secret-password")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def with_javascript() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    w.add_js("app.alert('hi');")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def handmade(stream: bytes, pages: int = 1) -> bytes:
    """A minimal valid PDF whose single content stream is exactly `stream` (offsets computed correctly)."""
    objs = [b"<</Type/Catalog/Pages 2 0 R>>",
            ("<</Type/Pages/Kids[" + " ".join(f"{3 + i} 0 R" for i in range(pages)) + f"]/Count {pages}>>").encode()]
    content_ref = 3 + pages
    for _ in range(pages):
        objs.append(f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents {content_ref} 0 R>>".encode())
    objs.append(b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream")
    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(buf)


def noisy_containing_js(mebibytes: float = 1.0) -> bytes:
    """Incompressible data that contains the three bytes /JS. V3 rejected files like this."""
    rng = random.Random(7)
    data = bytearray(rng.randbytes(int(mebibytes * 1024 * 1024)))
    data[1000:1003] = b"/JS"
    return handmade(bytes(data))


def plain_text() -> bytes:
    return ("This is not a PDF at all.\n" * 50).encode()


def png_like() -> bytes:
    return bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A]) + bytes(200)


def truncated(good: bytes) -> bytes:
    return good[: len(good) // 2]


def with_leading_junk(good: bytes) -> bytes:
    """Scanners and mail clients sometimes prepend bytes before %PDF-."""
    return b"\r\n" + good


def multipart_wrapped(good: bytes) -> bytes:
    """What a browser sends if it uploads a FormData body to a raw PUT URL (the V3 upload bug)."""
    boundary = b"----WebKitFormBoundaryX"
    return (b"--" + boundary + b'\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n'
            b"Content-Type: application/pdf\r\n\r\n" + good + b"\r\n--" + boundary + b"--\r\n")
