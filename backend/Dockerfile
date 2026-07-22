# Alpine, not debian-slim: the Debian rootfs alone is ~118 MB more on disk, and nothing here
# needs glibc. Measured on arm64 (RPi5) — 363 MB → 230 MB, `app.main` import 1.56s → 1.94s.
FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
# --only-binary=:all: is a guard, not an optimisation: every dependency currently ships a
# musllinux wheel, and this makes the build FAIL LOUDLY the day one stops. Without it pip
# silently falls back to building from source, which needs a Rust/C toolchain this image does
# not carry and takes about an hour on a Pi. Do not drop the flag to "fix" a failing build —
# a failure here means that dependency genuinely has no musl wheel and needs a decision.
#
# Bytecode is deliberately left compiled (no --no-compile): skipping it saves ~29 MB but costs
# ~1.6s on every start, which is the wrong trade for a long-running server.
#
# pip is 12 MB and is not needed once the dependencies are installed.
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
 && pip uninstall -y pip \
 && rm -rf /usr/local/lib/python3.12/site-packages/pip*

COPY app ./app

VOLUME /data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
