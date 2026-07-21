"""Upload extraction limits: bounded reads, a parse time budget, and the event loop
staying free (parsing runs in a worker thread)."""
import io
import time

from conftest import register  # noqa: F401  (kept for symmetry with the other suites)

from app.routers import extract as extract_router


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
