"""A file's hash that can neither hang nor run out of memory.

WHY THIS EXISTS. The completion gate compares FINDINGS.md's content with what it
held at dispatch (`findings_before`). The first version read the whole path with
`read_bytes()` inside `smokin tick`: a FIFO named FINDINGS.md hung the tick, and
a file larger than memory (or a symlink to /dev/zero) killed it with
MemoryError — and a stuck tick dispatches nothing, healthy tasks included.
Found by adversarial review (T16 in the suite-timing plan), 2026-09-16.

So: open without blocking, look at what was opened (not at the path, which can
change between a stat and an open), hash only a regular file, and read it in
chunks. Anything that cannot be hashed is named, never guessed.

  None                         absent, or (by default) an empty regular file
  "sha256:<64 hex>"            a readable, non-empty regular file
  "unhashable: <why>"          anything else — a FIFO, a device, a directory,
                               a permission error, a read error, a path that
                               cannot be opened at all, or a file over 4 GiB
"""
import hashlib
import os
import re
import stat

HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")
EMPTY_SHA = "sha256:" + hashlib.sha256(b"").hexdigest()
# LARGER THAN THIS IS NOT HASHED (decided 2026-09-17). Hashing never blocks, but
# its time grows with size: an 8 GiB sparse file made every `smokin status` take
# ~22s. Task artefacts are text; 4 GiB catches only the pathological.
MAX_BYTES = 4 << 30
_CHUNK = 1 << 20


def is_hash(value) -> bool:
    """A real `sha256:<64 hex>` and nothing else — `fullmatch`, because `$`
    also matches before a trailing newline and let "<hash>\\n" through."""
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def file_sha(path, empty_is_none: bool = True) -> "str | None":
    """Never raises. `empty_is_none=False` hashes an empty regular file to
    EMPTY_SHA — the form receipts have always recorded artifacts in."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as e:
        return f"unhashable: cannot open ({e.strerror or e.__class__.__name__})"
    except (ValueError, UnicodeError) as e:     # NUL in the path, a lone surrogate
        return f"unhashable: not an openable path ({e.__class__.__name__})"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return "unhashable: not a regular file"
        if st.st_size > MAX_BYTES:
            return "unhashable: larger than 4 GiB"
        h = hashlib.sha256()
        seen = 0
        while True:
            block = os.read(fd, _CHUNK)
            if not block:
                break
            seen += len(block)
            if seen > MAX_BYTES:                 # it grew while being read
                return "unhashable: larger than 4 GiB"
            h.update(block)
        if seen == 0 and empty_is_none:
            return None
        return "sha256:" + h.hexdigest()
    except OSError as e:
        return f"unhashable: cannot read ({e.strerror or e.__class__.__name__})"
    finally:
        os.close(fd)


def usable(value) -> bool:
    """A `findings_before` the content rule can trust: null or a real hash."""
    return value is None or is_hash(value)
