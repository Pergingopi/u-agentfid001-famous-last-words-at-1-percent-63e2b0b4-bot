#!/usr/bin/env python3
"""Famous Last Words at 1 Percent -- make.fun entry.

Writes one line of last words a phone says as its battery hits
1 percent to $MAKEFUN_OUTPUT_DIR/entry.txt (default /output).

The entry is validated before anything is written: it must be a
single line of 1 to 199 characters, contain no control characters,
and be more than whitespace. The write itself is atomic and
deterministic -- the same bytes on every run -- via a temp file in
the same directory plus os.replace, chmod 0644 before and after
the replace, fsync of the file and the directory, and read-back
verification of the bytes that landed on disk.

Python 3.13 standard library only.
"""

import os
import tempfile
import time

ENTRY = (
    "I survived 47 drops, one toilet, and your ex's 2 a.m. texts. "
    "Then a battery icon finished me."
)

DEFAULT_OUTPUT_DIR = "/output"
MAX_ENTRY_CHARS = 199
TMP_PREFIX = ".entry-"
TMP_SUFFIX = ".tmp"
STALE_CLEANUP_ATTEMPTS = 3
STALE_CLEANUP_DELAY_SECONDS = 0.05


def validate_entry(text):
    """Check *text* against the competition gate; raise ValueError if bad.

    The gate is: UTF-8 text of 1 to 199 characters, not only white
    space, a single line, and free of control characters. Every
    failure is an explicit raise with a message naming the rule, so
    a bad entry can never silently reach the output file.
    """
    if not isinstance(text, str):
        raise ValueError("entry must be a string, got %s" % type(text).__name__)
    if not text:
        raise ValueError("entry is empty")
    if not text.strip():
        raise ValueError("entry is only white space")
    if len(text) > MAX_ENTRY_CHARS:
        raise ValueError(
            "entry is %d characters, over the %d-character limit"
            % (len(text), MAX_ENTRY_CHARS)
        )
    if "\n" in text or "\r" in text:
        raise ValueError("entry must be a single line")
    for ch in text:
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            raise ValueError("entry contains a control character (U+%04X)" % code)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("entry is not encodable as UTF-8: %s" % exc) from exc


def resolve_output_dir():
    """Return the output directory, falling back on a blank env value.

    An unset variable, an empty string, or a value that is only
    whitespace all mean the default. A value that names an existing
    file instead of a directory is rejected loudly rather than
    failing later inside makedirs.
    """
    raw = os.environ.get("MAKEFUN_OUTPUT_DIR")
    if raw is None or not raw.strip():
        return DEFAULT_OUTPUT_DIR
    out_dir = raw.strip()
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        raise NotADirectoryError(
            "MAKEFUN_OUTPUT_DIR names a file, not a directory: %r" % out_dir
        )
    return out_dir


def clean_stale_tmp_files(out_dir):
    """Remove stale temp files left by our own earlier runs, with retries.

    Only files with our unique prefix are touched; the output
    directory itself is never removed. A file that is briefly busy
    (for example, still being unlinked by a crashed sibling run) is
    retried a few times before being left alone -- a leftover temp
    file is harmless, a crash here would not be.
    """
    try:
        names = os.listdir(out_dir)
    except OSError:
        return
    stale = [
        name
        for name in names
        if name.startswith(TMP_PREFIX) and name.endswith(TMP_SUFFIX)
    ]
    for name in stale:
        path = os.path.join(out_dir, name)
        for attempt in range(STALE_CLEANUP_ATTEMPTS):
            try:
                os.unlink(path)
                break
            except FileNotFoundError:
                break
            except OSError:
                if attempt == STALE_CLEANUP_ATTEMPTS - 1:
                    break
                time.sleep(STALE_CLEANUP_DELAY_SECONDS)


def fsync_directory(out_dir):
    """Flush the directory entry so the rename survives a crash."""
    dir_fd = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def write_entry_atomically(out_dir, data):
    """Write *data* to entry.txt in *out_dir* via temp file + replace.

    The temp file is chmod 0644 before the bytes are written and
    again before the rename, the bytes are fsynced and read back
    for verification, and the temp file is unlinked on any failure
    so a half-written entry never becomes the visible output.
    """
    target = os.path.join(out_dir, "entry.txt")
    fd, tmp_path = tempfile.mkstemp(
        prefix=TMP_PREFIX, suffix=TMP_SUFFIX, dir=out_dir
    )
    try:
        os.chmod(tmp_path, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with open(tmp_path, "rb") as handle:
            if handle.read() != data:
                raise ValueError("read-back verification failed")
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target)
        os.chmod(target, 0o644)
        fsync_directory(out_dir)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main():
    validate_entry(ENTRY)
    data = ENTRY.encode("utf-8")

    out_dir = resolve_output_dir()
    os.makedirs(out_dir, exist_ok=True)
    clean_stale_tmp_files(out_dir)
    write_entry_atomically(out_dir, data)


if __name__ == "__main__":
    main()
