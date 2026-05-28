# Install

bioflow needs **Python ≥ 3.9** and a reachable **Docker** daemon.  It
never installs bioinformatics tools on the host — each tool runs as a
sibling container pulled from BioContainers on first use.

## From a git checkout (development)

Use this when you want to edit recipes or tool YAMLs in place.

```bash
git clone https://github.com/hope9901/bioflow
cd bioflow
pip install -e .

docker info     # verify the daemon is reachable
```

## As a package

The tool registry is bundled into the wheel, so this works from any
directory:

```bash
pip install bioflow      # once published to PyPI
bioflow recipe list
```

## As a container

No Python setup needed — the orchestrator image ships with everything:

```bash
docker build -f docker/core/Dockerfile -t bioflow .

docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":/workspace \
  -v /refs:/refs \
  bioflow recipe run prokaryote_assembly \
    --r1 /workspace/R1.fq.gz --r2 /workspace/R2.fq.gz \
    --out /workspace/out
```

The container mounts the host Docker socket and launches each tool as a
**sibling** container (not Docker-in-Docker).

## Optional — LLM companion

```bash
bioflow setup                     # detect CPU/RAM/GPU, recommend a backend
bioflow setup --backend disabled  # explicit no-LLM mode (default)
bioflow setup --backend anthropic # cloud (needs ANTHROPIC_API_KEY)
bioflow setup --backend ollama    # local Ollama
```

Nothing is sent to any model until you opt in.

## Verify your machine

```bash
bioflow hw       # CPU / RAM / GPU / disk profile
bioflow tools    # all tools, grouped by hardware compatibility
```
