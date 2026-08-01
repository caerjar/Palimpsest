# Palimpsest — a self-contained image so anyone can run the app with one
# command. Bundles everything the app can use: git (section history), pandoc
# (Word/HTML/Markdown export), XeLaTeX + fonts (PDF export), and PyMuPDF (PDF
# import). Your books live OUTSIDE the image, in a host folder mounted at /data.
FROM python:3.13-slim

# System tools the app shells out to. Kept to what the features actually use.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        pandoc \
        texlive-xetex texlive-latex-recommended texlive-fonts-recommended \
        lmodern \
        fonts-texgyre fonts-noto-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Books are bind-mounted from the host and may be owned by the host user; let git
# operate on them without the "dubious ownership" refusal (history stays optional).
# Scoped to the workbench mount rather than '*', so the exemption covers the books
# this container is meant to touch and nothing else.
RUN git config --system --add safe.directory '/data' \
    && git config --system --add safe.directory '/data/*'

WORKDIR /app
# Copy the CODE and the book TEMPLATE only — never bundle anyone's books. The
# package is pip-installed so the image uses the exact same `pal` entry point and
# engine/_template layout that pipx/Homebrew users get. [pdf] pulls in PyMuPDF for
# the "import a PDF" feature.
COPY pyproject.toml MANIFEST.in README.md LICENSE /app/
COPY palimpsest /app/palimpsest
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN pip install --no-cache-dir '.[pdf]' && chmod +x /app/docker-entrypoint.sh

ENV PAL_HOME=/data \
    PAL_BIND=0.0.0.0 \
    PAL_NO_BROWSER=1 \
    PAL_PDF_HEADER=/app/palimpsest/engine/assets/header-linux.tex \
    PORT=8137 \
    PYTHONUNBUFFERED=1

EXPOSE 8137
VOLUME ["/data"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
