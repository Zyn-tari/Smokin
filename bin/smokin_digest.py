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
                               cannot be opened at all, a file over 4 GiB, or
                               one that states size 0 and keeps reading

`file_id` is the cheap half of the same job: a regular file's identity, so a
receipt can tell an unchanged artifact from a changed one without hashing it at
all. See its docstring for why the fields are only ever compared for equality.
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
# HOW MUCH IS READ FROM A FILE THAT STATES SIZE 0. See file_sha.
_ZERO_SIZED_MAX = 1 << 20
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
        # A REGULAR FILE THAT REPORTS SIZE 0 IS NOT NECESSARILY EMPTY. Every
        # file under /proc is a regular file of stated size 0 that yields
        # content when read, and some yield a great deal of it. `st_size` is
        # the only bound we have before reading, so when it says 0 the read is
        # bounded separately and generously: an artifact that is really empty
        # reads 0 bytes and never meets this, and one that keeps producing is
        # named rather than followed.
        ceiling = MAX_BYTES if st.st_size else _ZERO_SIZED_MAX
        h = hashlib.sha256()
        seen = 0
        while True:
            block = os.read(fd, _CHUNK)
            if not block:
                break
            seen += len(block)
            if seen > ceiling:                   # it grew while being read
                return ("unhashable: larger than 4 GiB" if ceiling == MAX_BYTES
                        else "unhashable: reports size 0 but keeps reading")
            h.update(block)
        if seen == 0 and empty_is_none:
            return None
        return "sha256:" + h.hexdigest()
    except OSError as e:
        return f"unhashable: cannot read ({e.strerror or e.__class__.__name__})"
    finally:
        os.close(fd)


# WHAT IDENTIFIES A FILE, for the receipt's artifact_ids. Device and inode say
# it is the same file; size, mtime and ctime say it has not been written since.
# ctime is in there because it moves on a rename or a permission change that
# leaves mtime alone. THESE ARE COMPARED FOR EQUALITY AND NOTHING ELSE — never
# ordered, never subtracted. This machine's wall clock steps backwards by about
# two seconds every few minutes (suite-timing T13), so "newer" is not a
# question a file's timestamps can answer here.
_ID_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")


def file_id(path) -> "dict | None":
    """A regular file's identity, or None when there is nothing to identify —
    it is absent, it is not a regular file, or it cannot be opened. Never
    raises. None from here means "fall back to the hash", and a None on one
    side of a comparison is a difference, which is the safe direction.

    fstat, not stat: the path can be replaced between a stat and an open, and
    the identity must belong to the file that would actually be read."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, ValueError, UnicodeError):
        return None
    try:
        st = os.fstat(fd)
    except OSError:
        return None
    finally:
        os.close(fd)
    if not stat.S_ISREG(st.st_mode):
        return None
    return {f[3:]: getattr(st, f) for f in _ID_FIELDS}


def same_id(a, b) -> bool:
    """True only when both are identities and every field matches. Anything
    else — a missing side, a value JSON turned into something else — is a
    difference."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    keys = [f[3:] for f in _ID_FIELDS]
    if set(a) != set(keys) or set(b) != set(keys):
        return False
    return all(a[k] == b[k] for k in keys)


def usable(value) -> bool:
    """A `findings_before` the content rule can trust: null or a real hash."""
    return value is None or is_hash(value)
