"""Document text extraction: pulls the text out of an uploaded file and returns it.

Feeds text-based documents (PDF/docx/txt/code) to the model as lossless text rather than
vision OCR. The extracted text is attached to the message by the frontend.
"""
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.auth import get_current_user

router = APIRouter(prefix="/api", tags=["extract"], dependencies=[Depends(get_current_user)])

MAX_CHARS = 100_000  # cap, so the context is not blown out
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


@router.post("/extract")
async def extract(file: UploadFile):
    """Extracts the file's text. Returns {name, text, truncated}."""
    name = file.filename or "file"
    lower = name.lower()
    data = await file.read()
    try:
        if lower.endswith(".pdf"):
            text = _extract_pdf(data)
        elif lower.endswith(".docx"):
            text = _extract_docx(data)
        elif lower.endswith(TEXT_EXTS) or (file.content_type or "").startswith("text/"):
            text = data.decode("utf-8", errors="replace")
        else:
            raise HTTPException(400, f"Unsupported file type: {name}")
    except HTTPException:
        raise
    except Exception as e:  # corrupt / unparseable file
        raise HTTPException(400, f"Could not extract text ({name}): {e}")

    text = text.strip()
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS] + "\n\n[... truncated ...]"
    return {"name": name, "text": text, "truncated": truncated}
