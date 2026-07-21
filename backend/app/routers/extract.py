"""Document text extraction: pulls the text out of an uploaded file and returns it.

Feeds text-based documents (PDF/docx/txt/code) to the model as lossless text rather than
vision OCR. The extracted text is attached to the message by the frontend.
"""
import asyncio
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.auth import get_current_user
from app.extract_worker import MAX_CHARS

router = APIRouter(prefix="/api", tags=["extract"], dependencies=[Depends(get_current_user)])

# Upload cap. Parsing costs RAM/CPU on top of the raw bytes, concurrent uploads multiply it,
# and the output is capped at MAX_CHARS anyway — beyond ~10 MB nothing is gained.
# nginx enforces the same 10M on this exact route so an oversize body is refused at the edge;
# the check below is the backend's own guarantee, independent of any proxy in front.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# pypdf/python-docx parse UNTRUSTED files and have a long history of crafted-file hangs, so
# they run in a throwaway process under a hard time budget. When the budget runs out the
# process is KILLED: the request and the capability both come back.
#
# It used to be a worker thread, and that budget freed only the request — Python cannot kill a
# thread, so a hung parse kept its worker for good and `asyncio.to_thread`'s default executor
# (min(32, cpu+4), i.e. 8 threads on a 4-core host) meant enough concurrent hangs took
# /api/extract down until the process restarted. A bigger pool would only have raised the
# number of hangs needed.
PARSE_TIMEOUT = 30.0
# Spawned per parse. `python -m` puts the working directory on sys.path, hence cwd — the
# worker is `app.extract_worker` relative to the directory holding the `app` package.
_WORKER_ARGV = [sys.executable, "-m", "app.extract_worker"]
_WORKER_CWD = Path(__file__).resolve().parents[2]
# A process per upload needs a ceiling that a thread pool used to provide for free: the old
# `to_thread` executor capped this at 8 by accident of its own sizing. Without one, N
# concurrent uploads are N interpreters each holding a whole parsed document. Waiting for a
# slot is deliberately not on a timer — a parse cannot outlive PARSE_TIMEOUT, so the queue
# always drains, and a client that gave up has already gone (which kills its child).
MAX_CONCURRENT_PARSES = 4
_parse_slots = asyncio.Semaphore(MAX_CONCURRENT_PARSES)
TEXT_EXTS = (
    ".txt", ".md", ".markdown", ".csv", ".json", ".yml", ".yaml", ".log",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".html", ".css", ".xml", ".sql", ".toml", ".ini",
)


def _classify(lower_name: str, content_type: str | None) -> str:
    """Picks the parser, or rejects the file before anything is spawned."""
    if lower_name.endswith(".pdf"):
        return "pdf"
    if lower_name.endswith(".docx"):
        return "docx"
    if lower_name.endswith(TEXT_EXTS) or (content_type or "").startswith("text/"):
        return "text"
    raise HTTPException(400, f"Unsupported file type: {lower_name}")


async def _parse_in_subprocess(kind: str, data: bytes, name: str) -> str:
    """Runs the parser in a killable child. Raises HTTPException(400) on hang or bad input."""
    async with _parse_slots:
        return await _spawn_and_read(kind, data, name)


async def _spawn_and_read(kind: str, data: bytes, name: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *_WORKER_ARGV, kind,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=_WORKER_CWD,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(data), timeout=PARSE_TIMEOUT)
    except TimeoutError:  # the parse outlived its budget (crafted/huge file)
        raise HTTPException(400, f"Could not extract text ({name}): parsing took too long")
    finally:
        # Runs for the timeout AND for a client that walked away mid-upload (CancelledError):
        # either way the child is still chewing on the file and nothing is waiting for it.
        if proc.returncode is None:
            proc.kill()
            await proc.wait()

    if proc.returncode != 0:  # corrupt / unparseable file
        # Last line only, and clipped: the parsers log their own complaints to stderr on the
        # way down (pypdf emits an "invalid pdf header" line of its own), and all of it is
        # attacker-shaped text. The worker's own message is written last, so that is the line.
        lines = err.decode("utf-8", errors="replace").strip().splitlines()
        detail = lines[-1][:300] if lines else f"exit {proc.returncode}"
        raise HTTPException(400, f"Could not extract text ({name}): {detail}")
    return out.decode("utf-8", errors="replace")


@router.post("/extract")
async def extract(file: UploadFile):
    """Extracts the file's text. Returns {name, text, truncated}."""
    name = file.filename or "file"
    kind = _classify(name.lower(), file.content_type)
    # Bounded read: the PARSER never sees more than MAX_UPLOAD_BYTES+1 bytes, whatever was
    # uploaded (UploadFile.size is not reliably populated — measure, don't trust).
    # It does NOT bound what the upload itself costs: Starlette's multipart parser has already
    # consumed the whole body into a SpooledTemporaryFile (RAM up to 1 MB, then disk) before
    # this function runs. Bounding the body is nginx's job — see client_max_body_size on
    # `location = /api/extract` in frontend/nginx.conf.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large ({name}): the limit is {MAX_UPLOAD_BYTES // 1024 // 1024} MB")

    if kind == "text":
        # No parser, no subprocess: decoding bounded bytes cannot hang, so there is nothing to
        # kill and a process per pasted snippet would be pure overhead. It still goes off the
        # loop — 10 MB of decoding is short but not free.
        text = await asyncio.to_thread(data.decode, "utf-8", "replace")
    else:
        text = await _parse_in_subprocess(kind, data, name)

    text = text.strip()
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS] + "\n\n[... truncated ...]"
    return {"name": name, "text": text, "truncated": truncated}
