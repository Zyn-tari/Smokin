"""Elapsed time that a wall-clock step cannot move.

THE DEFECT, measured 2026-09-16. Every elapsed-time decision Smokin made was a
difference of two `time.time()` readings — the reap budget, a receipt's
`wall_s`, the elapsed time STATUS.json reports, `wait`'s deadline. On the WSL
machine this was found on, the wall clock is stepped back about 2.2 seconds
every few minutes (`systemd-journald: Time jumped backwards`; `timesyncd`
reports offset −2.2s against a host clock that does not sync). A step inside a
budget moves the reap: backwards and a dead worker is reaped late, forwards and
a live one is reaped early. Two intermittent suite failures that day were this,
and one receipt came out with `ended` before `started` and `wall_s: -1.0`.

WHY BOOTTIME AND NOT `time.monotonic()`. Both are immune to steps. BOOTTIME also
counts time the machine spent suspended, which is what a budget measured in
wall-clock seconds always meant; MONOTONIC would silently stretch a budget by
the length of every host sleep. Where BOOTTIME does not exist (it is Linux-only)
the plain monotonic clock is used, and the record says which.

WHY THE BOOT ID. The start is recorded by the process that dispatches and read
by a later one, so the reading has to mean the same thing in both. A monotonic
clock restarts at boot; a record from before a reboot compared against a reading
after it is nonsense. The record carries the boot it was taken in, and when the
boot differs — or cannot be read, or the clocks differ, or the difference is
negative — the old wall-clock difference is used and the caller is told so.
Falling back is the old behaviour, never a new failure.
"""
import time
from pathlib import Path

_BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def _read():
    clk = getattr(time, "CLOCK_BOOTTIME", None)
    if clk is not None:
        try:
            return "boottime", time.clock_gettime(clk)
        except OSError:
            pass
    return "monotonic", time.monotonic()


def boot_id():
    try:
        return _BOOT_ID.read_text().strip() or None
    except OSError:
        return None


def stamp() -> dict:
    """What a dispatch record carries so a later process can measure from it."""
    name, value = _read()
    return {"started_mono": value, "mono_clock": name, "boot_id": boot_id()}


def elapsed(rec: dict, default_epoch: float = 0.0):
    """Seconds since `rec` started, and how they were measured.

    Returns (seconds, clock) where clock is "boottime" or "monotonic", or
    "wall-fallback: <why>" when the record cannot be measured monotonically.
    """
    wall = time.time() - rec.get("started_epoch", default_epoch)
    mono = rec.get("started_mono")
    if mono is None:
        return wall, "wall-fallback: the record carries no monotonic start"
    here = boot_id()
    if here is None or rec.get("boot_id") != here:
        return wall, "wall-fallback: a different or unknown boot"
    name, value = _read()
    if name != rec.get("mono_clock"):
        return wall, "wall-fallback: the record was taken on a different clock"
    d = value - mono
    if d < 0:
        return wall, "wall-fallback: the monotonic difference is negative"
    return d, name
