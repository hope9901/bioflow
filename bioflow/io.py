"""bioflow.io — operational quirk absorption layer.

A growing list of session-tested footguns is centralised here so recipes
and stages can stay short.  Every function has a deliberately boring
contract; nothing is "smart".

Quirks this module absorbs
--------------------------
* **CRLF / mixed line endings.**  ``write_text`` always emits LF only.
  CAFE5 silently miscounted columns when handed a CRLF traits file in
  session 1; never again.
* **Encoding wobble.**  Korean Windows cp949 consoles crash on Rich's
  ✓/✗ glyphs.  ``read_text`` defaults to UTF-8 with ``errors="replace"``
  so a stray byte never aborts a long pipeline.
* **Half-written outputs on crash.**  ``write_text`` / ``write_bytes``
  use the temp-file + rename pattern so SIGINT mid-write leaves the
  previous file intact.
* **Flaky HTTPS endpoints.**  ``download_url`` does exponential back-off
  on 5xx and connection errors, validates ``Content-Length`` after the
  stream completes, and cleans up partial files on failure.
* **"URL too long" 414 responses.**  ``batched_urls`` chunks an
  iterable of accessions into URLs whose final length stays below a
  configurable budget — mirrors the NCBI Datasets fix from session 1
  but generalised.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional, Tuple, TypeVar

from bioflow.core.logger import get_logger

log = get_logger()

__all__ = [
    "write_text",
    "read_text",
    "write_bytes",
    "read_bytes",
    "atomic_replace",
    "download_url",
    "retry",
    "batched_urls",
    "DownloadError",
]


# ---------------------------------------------------------------------------
# File IO
# ---------------------------------------------------------------------------

def write_text(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Write *content* to *path* — always LF, UTF-8, atomic.

    Uses a tempfile in the same directory + ``os.replace`` so a crash
    mid-write never leaves a half-written file at *path*.  Newlines in
    *content* are normalised to LF, regardless of the host OS or the
    string the caller passed in.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Normalise CRLF / CR to LF
    normalised = content.replace("\r\n", "\n").replace("\r", "\n")
    fd, tmp = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
    )
    try:
        # newline="" tells Python NOT to translate \n → os.linesep again.
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(normalised)
        os.replace(tmp, str(target))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def read_text(
    path: Path | str,
    *,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> str:
    """Read *path* as text — UTF-8 by default, never crashes on a stray byte.

    The default ``errors="replace"`` means an undecodable byte becomes
    ``U+FFFD`` rather than raising.  Use ``errors="strict"`` if you need
    decoding to fail loudly.
    """
    return Path(path).read_text(encoding=encoding, errors=errors)


def write_bytes(path: Path | str, data: bytes) -> Path:
    """Atomically write *data* to *path* (tempfile + rename)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, str(target))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def read_bytes(path: Path | str) -> bytes:
    return Path(path).read_bytes()


def atomic_replace(src: Path | str, dst: Path | str) -> None:
    """Cross-platform ``mv``: works across drives, falls back to copy+remove."""
    src_p, dst_p = Path(src), Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(str(src_p), str(dst_p))
    except OSError:
        # Different filesystem on Windows — fall back to copy+remove
        shutil.copy2(str(src_p), str(dst_p))
        src_p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Retry decorator + helper
# ---------------------------------------------------------------------------

T = TypeVar("T")


def retry(
    *,
    attempts: int = 3,
    initial_delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 60.0,
    exceptions: Tuple[type, ...] = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Exponential-backoff retry decorator for transient failures.

    Examples
    --------
    >>> @retry(attempts=5, exceptions=(urllib.error.URLError,))
    ... def fetch(url): ...

    The wrapped function re-raises the *last* caught exception when
    ``attempts`` is exhausted.  ``on_retry(attempt_idx, exc)`` is called
    just before each sleep; useful for logging.
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exc: Optional[Exception] = None
            for i in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if i == attempts:
                        break
                    if on_retry is not None:
                        on_retry(i, exc)
                    log.warning(
                        f"retry: {fn.__name__} attempt {i}/{attempts} "
                        f"failed ({exc!r}); sleeping {delay:.1f}s"
                    )
                    time.sleep(min(delay, max_delay))
                    delay *= backoff
            assert last_exc is not None
            raise last_exc
        wrapper.__wrapped__ = fn   # so functools.wraps-style intros work
        wrapper.__name__ = getattr(fn, "__name__", "retry_wrapper")
        wrapper.__doc__ = getattr(fn, "__doc__", None)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# HTTP download with retry + Content-Length validation
# ---------------------------------------------------------------------------

class DownloadError(RuntimeError):
    """Raised when a URL download cannot complete after retries."""


_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


def download_url(
    url: str,
    dest: Path | str,
    *,
    timeout: int = 600,
    chunk_size: int = 1 << 17,
    attempts: int = 3,
    initial_delay: float = 2.0,
    progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    headers: Optional[dict] = None,
    _opener: Optional[Callable] = None,
) -> Path:
    """Stream *url* to *dest* with exponential backoff and size validation.

    On 5xx / connection error the request is retried; on 4xx (other than
    408 / 429) it fails immediately.  Truncated downloads (bytes received
    < ``Content-Length``) raise :class:`DownloadError` and the partial
    file is cleaned up.

    Returns the destination path on success.
    """
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    opener = _opener or urllib.request.urlopen

    delay = initial_delay
    last_exc: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with opener(req, timeout=timeout) as resp:
                total_raw = resp.headers.get("Content-Length") if hasattr(resp, "headers") else None
                total = int(total_raw) if total_raw else None
                written = 0
                with target.open("wb") as fh:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        fh.write(chunk)
                        written += len(chunk)
                        if progress_callback:
                            progress_callback(written, total)

            if total is not None and written != total:
                target.unlink(missing_ok=True)
                raise DownloadError(
                    f"truncated: expected {total} bytes, got {written}"
                )
            return target

        except urllib.error.HTTPError as exc:
            target.unlink(missing_ok=True)
            transient = exc.code in _TRANSIENT_STATUS
            last_exc = exc
            if not transient or attempt == attempts:
                # 4xx (other than 408/429) — fail fast
                raise DownloadError(
                    f"HTTP {exc.code} on {url}: {exc.reason}"
                ) from exc
            log.warning(
                f"HTTP {exc.code} on attempt {attempt}/{attempts}; "
                f"sleeping {delay:.1f}s"
            )
            time.sleep(delay)
            delay *= 2
        except (urllib.error.URLError, TimeoutError, ConnectionError, DownloadError) as exc:
            target.unlink(missing_ok=True)
            last_exc = exc
            if attempt == attempts:
                break
            log.warning(
                f"transient {exc!r} on attempt {attempt}/{attempts}; "
                f"sleeping {delay:.1f}s"
            )
            time.sleep(delay)
            delay *= 2

    raise DownloadError(
        f"giving up on {url} after {attempts} attempts: {last_exc!r}"
    )


# ---------------------------------------------------------------------------
# URL batching (HTTP 414 fix, generalised)
# ---------------------------------------------------------------------------

def batched_urls(
    items: Iterable[str],
    template: str,
    *,
    max_url_length: int = 3500,
    separator: str = ",",
    placeholder: str = "{ITEMS}",
) -> Iterator[Tuple[str, list]]:
    """Yield ``(url, batch_of_items)`` pairs whose URL stays under a budget.

    *template* must contain *placeholder* exactly once.  Items are joined
    with *separator* and substituted in.  When the next item would push
    the URL above *max_url_length*, the current batch is yielded and a
    new one starts.

    Example
    -------
    >>> for url, batch in batched_urls(
    ...     ["GCF_001", "GCF_002", "GCF_003"],
    ...     template="https://api.example.com/lookup/{ITEMS}",
    ...     max_url_length=80,
    ... ):
    ...     fetch(url)
    """
    if placeholder not in template:
        raise ValueError(f"template must contain {placeholder!r}")

    items_list = list(items)
    if not items_list:
        return

    fixed_overhead = len(template) - len(placeholder)
    batch: list = []
    current_len = 0

    for item in items_list:
        item_len = len(item) + (len(separator) if batch else 0)
        if batch and (fixed_overhead + current_len + item_len) > max_url_length:
            yield template.replace(placeholder, separator.join(batch)), list(batch)
            batch = [item]
            current_len = len(item)
        else:
            batch.append(item)
            current_len += item_len

    if batch:
        yield template.replace(placeholder, separator.join(batch)), list(batch)
