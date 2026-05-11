# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x (latest) | Yes |
| < 0.1.0 | No |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Send a report to the maintainer's email (see `pyproject.toml`) with:

1. A description of the vulnerability and its potential impact.
2. Steps to reproduce.
3. Any suggested fix, if you have one.

You will receive an acknowledgment within 72 hours.  We aim to release a fix
within 14 days of a confirmed report, or to communicate why a longer timeline
is necessary.

## Scope

bioflow runs entirely on a single local workstation.  Relevant security
concerns include:

- **Malicious tool YAMLs** — a crafted `command_template` that runs arbitrary
  commands inside a container.  bioflow does not sandbox the container itself
  beyond standard Docker isolation.
- **LLM backend credentials** — API keys stored in `~/.bioflow/config.yaml`
  or environment variables.  bioflow never logs these, but standard file-system
  permissions apply.
- **git push credentials** — bioflow delegates to the OS git credential store;
  it never stores or transmits tokens.

Out of scope:

- Docker Engine vulnerabilities (report to Docker).
- Container image vulnerabilities (report to BioContainers / the image
  maintainer).
- Issues in third-party Python dependencies (report upstream).
