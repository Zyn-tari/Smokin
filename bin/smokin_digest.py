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

  None                         absent, or an empty regular file
  "sha256:<64 hex>"            a readable, non-empty regular file
  "unhashable: <why>"          anything else — a FIFO, a device, a directory,
                               a permission error, a read error
"""
import hashlib
import os
import re
import stat

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CHUNK = 1 << 20


def file_sha(path) -> "str | None":
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as e:
        return f"unhashable: cannot open ({e.strerror or e.__class__.__name__})"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return "unhashable: not a regular file"
        if st.st_size == 0:
            return None
        h = hashlib.sha256()
        while True:
            block = os.read(fd, _CHUNK)
            if not block:
                break
            h.update(block)
        return "sha256:" + h.hexdigest()
    except OSError as e:
        return f"unhashable: cannot read ({e.strerror or e.__class__.__name__})"
    finally:
        os.close(fd)


def usable(value) -> bool:
    """A `findings_before` the content rule can trust: null or a real hash."""
    return value is None or (isinstance(value, str) and bool(HASH_RE.match(value)))
