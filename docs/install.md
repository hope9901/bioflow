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
pip install bioflowkit    # PyPI distribution name (`bioflow` was taken in 2018)
bioflow doctor            # CLI + Python import stay `bioflow`
bioflow recipe list
```

Only the `pip install` argument differs from the brand — `from bioflow
import stage`, the `bioflow` CLI command, and the GitHub URL are
unchanged.

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

The first command you should run after installing:

```bash
bioflow doctor          # 12-point self-check; exits non-zero on FAIL
bioflow doctor --json   # machine-readable, for CI
bioflow doctor -v       # include per-check detail (paths, versions, …)
```

`doctor` confirms that Python, the Docker CLI + daemon, the docker socket
(sibling-container path), CPU / RAM / disk, the registry, and your home
+ workspace directories are all usable.  Each failure prints a one-line
fix hint.

Then the deeper hardware-aware inspectors:

```bash
bioflow hw       # CPU / RAM / GPU / disk profile (JSON)
bioflow tools    # all tools, grouped by hardware compatibility
```

### What `doctor` checks

| Check | When it FAILs | Common fix |
|---|---|---|
| `python`         | Python < 3.9                                 | Recreate the venv on a newer interpreter |
| `arch`           | machine not in {`x86_64`, `arm64`} (warn)    | Use an Intel/AMD or Apple-Silicon host |
| `docker_cli`     | `docker` not on PATH                          | Install Docker Desktop / docker engine |
| `docker_daemon`  | `docker info` non-zero                        | Start Docker Desktop / `systemctl start docker` |
| `docker_socket`  | `/var/run/docker.sock` unreadable (Linux/Mac) | `usermod -aG docker $USER`, new shell |
| `cpu`            | < 2 logical CPUs                              | Pick a bigger host |
| `ram`            | < 4 GB total RAM                              | Pick a bigger host (≥ 8 GB recommended) |
| `disk`           | < 10 GB free in the workspace                 | `--workspace <bigger-disk>` |
| `registry`       | 0 tools loaded or schema errors               | Re-clone or `pip install --force-reinstall` |
| `home_config`    | `~/.bioflow/` not writable                    | Fix ownership / permissions |
| `workspace`      | cwd not writable                              | Pick a writable `--workspace` |
| `gpu`            | Never fails (informational)                   | — |

