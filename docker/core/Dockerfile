# bioflow orchestrator (core) image.
# Runs as a sibling container: mounts the host Docker socket and launches
# per-tool containers. Does NOT embed bioinformatics tools itself.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates docker.io \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY bioflow ./bioflow
COPY registry ./registry

RUN pip install --upgrade pip && pip install .

# Shared volumes: workflow I/O, reference DBs.
VOLUME ["/workspace", "/refs"]

ENTRYPOINT ["bioflow"]
CMD ["--help"]
