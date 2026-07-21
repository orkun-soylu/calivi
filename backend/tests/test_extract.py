"""Upload extraction limits: bounded reads, a parse time budget, and the event loop
staying free (parsing runs in a worker thread)."""
import io
import time

from app.routers import extract as extract_router


def _minimal_pdf(text: str) -> bytes:
    """A standards-compliant single-page PDF containing `text`.

    Hand-built rather than pulled from a fixture or a generator library: the point is to
    exercise pypdf's real parsing path with no extra dependency, and to keep the bytes
    readable so a future failure can be diagnosed here instead of in a binary blob.
    """
    content = b"BT /F1 24 Tf 72 700 Td (" + text.encode("ascii") + b") Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref_at)
    return bytes(out)


async def test_extract_requires_login(client):
    resp = await client.post("/api/extract", files={"file": ("a.txt", b"hi", "text/plain")})
    assert resp.status_code == 401


async def test_text_file_round_trip(admin):
    resp = await admin.post("/api/extract", files={"file": ("a.txt", b"hello calivi", "text/plain")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "hello calivi" and body["truncated"] is False


async def test_oversize_upload_is_rejected(admin, monkeypatch):
    """The read is capped: more than MAX_UPLOAD_BYTES never reaches memory or the parser."""
    monkeypatch.setattr(extract_router, "MAX_UPLOAD_BYTES", 100)
    resp = await admin.post("/api/extract", files={"file": ("big.txt", b"x" * 101, "text/plain")})
    assert resp.status_code == 413


async def test_parse_timeout_returns_400_instead_of_hanging(admin, monkeypatch):
    """A parser that outlives its budget loses the request — the loop stays free."""
    monkeypatch.setattr(extract_router, "PARSE_TIMEOUT", 0.1)

    def hang(_data: bytes) -> str:
        time.sleep(5)
        return "never"

    monkeypatch.setattr(extract_router, "_extract_pdf", hang)
    resp = await admin.post("/api/extract", files={"file": ("evil.pdf", b"%PDF-1.4", "application/pdf")})
    assert resp.status_code == 400 and "too long" in resp.json()["detail"]


async def test_valid_pdf_round_trip(admin):
    """Guards the pypdf API surface across upgrades.

    Everything else about PDFs is tested through failure paths (corrupt input, timeouts),
    which keep passing even if `PdfReader` / `extract_text()` change shape — the bump from
    pypdf 5 to 6 went in with nothing asserting that a *valid* PDF still yields its text.
    """
    resp = await admin.post(
        "/api/extract",
        files={"file": ("doc.pdf", _minimal_pdf("Hello Calivi"), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    assert "Hello Calivi" in resp.json()["text"]


async def test_corrupt_pdf_is_a_400_not_a_500(admin):
    resp = await admin.post("/api/extract", files={"file": ("broken.pdf", b"not a pdf", "application/pdf")})
    assert resp.status_code == 400


async def test_docx_round_trip_through_the_worker_thread(admin):
    """End-to-end through asyncio.to_thread: a real docx parses and yields its text."""
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("merhaba calivi")
    doc.save(buf)
    resp = await admin.post(
        "/api/extract",
        files={"file": ("doc.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 200 and "merhaba calivi" in resp.json()["text"]


async def test_unsupported_extension_is_rejected(admin):
    resp = await admin.post("/api/extract", files={"file": ("a.exe", b"MZ", "application/octet-stream")})
    assert resp.status_code == 400
