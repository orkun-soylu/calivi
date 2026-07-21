"""Parses one uploaded document, in a process of its own that can be killed.

Run as `python -m app.extract_worker <pdf|docx>`: the file's bytes arrive on **stdin**, the
extracted text leaves on **stdout**, and a parse failure is a non-zero exit with a short
message on stderr.

Why a separate process at all: `pypdf` and `python-docx` parse untrusted files and have a long
history of crafted-file hangs. In a worker *thread* a hang is permanent — Python cannot kill a
thread — so the request could be abandoned but the thread never came back. Here the parent
sends SIGKILL and the capability is restored (see `routers/extract.py::_parse_in_subprocess`).

Kept free of app imports on purpose: no FastAPI, no database, no config. Starting this costs
one interpreter plus the parser import, and pulling the app in would make that much worse.
"""
import sys

# The parent applies the same number when it decides whether to flag the response as
# truncated, so the cap lives here, next to the only code that can produce more.
MAX_CHARS = 100_000


def extract_pdf(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def extract_docx(data: bytes) -> str:
    import io

    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


PARSERS = {"pdf": extract_pdf, "docx": extract_docx}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in PARSERS:
        print(f"usage: {argv[0]} <{'|'.join(PARSERS)}>", file=sys.stderr)
        return 2

    data = sys.stdin.buffer.read()
    try:
        text = PARSERS[argv[1]](data)
    except Exception as e:  # corrupt or unparseable — the parent turns this into a 400
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    # Stripped and capped here rather than in the parent: everything past the cap is discarded
    # anyway, and sending it would mean piping a whole crafted-PDF text bomb between processes.
    # One character past the cap is kept so the parent can still tell that truncation happened.
    sys.stdout.buffer.write(text.strip()[: MAX_CHARS + 1].encode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
