"""Document text extraction: pulls the text out of an uploaded file and returns it.

Feeds text-based documents (PDF/docx/txt/code) to the model as lossless text rather than
vision OCR. The extracted text is attached to the message by the frontend.
"""
import asyncio
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.auth import get_current_user

router = APIRouter(prefix="/api", tags=["extract"], dependencies=[Depends(get_current_user)])

MAX_CHARS = 100_000  # cap, so the context is not blown out
# Upload cap. Parsing costs RAM/CPU on top of the raw bytes, concurrent uploads multiply it,
# and the output is capped at MAX_CHARS anyway — beyond ~10 MB nothing is gained.
# nginx enforces the same 10M on this exact route so an oversize body is refused at the edge;
# the check below is the backend's own guarantee, independent of any proxy in front.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# pypdf/python-docx parse UNTRUSTED files and have a long history of crafted-file hangs —
# they run in a worker thread (CPU-bound; must not block the event loop) under a hard time
# budget. The budget cannot kill the thread (Python has no way to), it frees the request
# and the loop; the durable fix for the hangs is keeping pypdf current (requirements.txt).
PARSE_TIMEOUT = 30.0
TEXT_EXTS = (
    ".txt", ".md", ".markdown", ".csv", ".json", ".yml", ".yaml", ".log",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".html", ".css", ".xml", ".sql", ".toml", ".ini",
)


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_text(lower_name: str, data: bytes, content_type: str | None) -> str:
    """Sync dispatch — runs in a worker thread (see PARSE_TIMEOUT)."""
    if lower_name.endswith(".pdf"):
        return _extract_pdf(data)
    if lower_name.endswith(".docx"):
        return _extract_docx(data)
    if lower_name.endswith(TEXT_EXTS) or (content_type or "").startswith("text/"):
        return data.decode("utf-8", errors="replace")
    raise HTTPException(400, f"Unsupported file type: {lower_name}")


@router.post("/extract")
async def extract(file: UploadFile):
    """Extracts the file's text. Returns {name, text, truncated}."""
    name = file.filename or "file"
    lower = name.lower()
    # Bounded read: the PARSER never sees more than MAX_UPLOAD_BYTES+1 bytes, whatever was
    # uploaded (UploadFile.size is not reliably populated — measure, don't trust).
    # It does NOT bound what the upload itself costs: Starlette's multipart parser has already
    # consumed the whole body into a SpooledTemporaryFile (RAM up to 1 MB, then disk) before
    # this function runs. Bounding the body is nginx's job — see client_max_body_size on
    # `location = /api/extract` in frontend/nginx.conf.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large ({name}): the limit is {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_extract_text, lower, data, file.content_type),
            timeout=PARSE_TIMEOUT,
        )
    except HTTPException:
        raise
    except TimeoutError:  # the parse outlived its budget (crafted/huge file)
        raise HTTPException(400, f"Could not extract text ({name}): parsing took too long")
    except Exception as e:  # corrupt / unparseable file
        raise HTTPException(400, f"Could not extract text ({name}): {e}")

    text = text.strip()
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS] + "\n\n[... truncated ...]"
    return {"name": name, "text": text, "truncated": truncated}
