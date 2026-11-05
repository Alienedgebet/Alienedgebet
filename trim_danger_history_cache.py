#!/usr/bin/env python3
# One-shot memory-safe trim of danger_history_cache.json (2026-09-20).

import os
import re
import sys
import shutil
import time

TARGET = "/var/www/backend/data/danger_history_cache.json"
BACKUP = "/var/www/backend/data/danger_history_cache.json.bak-20260920"
CHUNK = 4 * 1024 * 1024
AT_RE = re.compile(rb'"at"\s*:\s*([0-9]+(?:\.[0-9]+)?)')


def scan_head(path, want):
    """Scan only the first ~`want` entries (file is written newest-first,
    so a head scan yields the newest entries). Returns list of
    (ts, start_byte, end_byte_exclusive, key_bytes) plus bytes consumed."""
    entries = []
    consumed = 0
    with open(path, "rb") as f:
        if f.read(1) != b"{":
            raise SystemExit("unexpected file head")
        pos = 1
        depth = 1
        entry_start = None
        top_key = bytearray()      # bytes of the CURRENT top-level key
        cur_key = b""              # frozen key of the entry being scanned
        in_top_key = False
        in_str = False
        esc = False
        sample = bytearray()
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            base = pos
            pos += len(chunk)
            i = 0
            n = len(chunk)
            stop = False
            while i < n:
                b = chunk[i]
                if entry_start is not None and len(sample) < 200:
                    sample.append(b)
                if in_str:
                    if esc:
                        esc = False
                    elif b == 0x5C:
                        esc = True
                    elif b == 0x22:            # close quote
                        in_str = False
                        in_top_key = False
                    elif in_top_key:
                        top_key.append(b)
                else:
                    if b == 0x22:              # open quote
                        in_str = True
                        if depth == 1:
                            in_top_key = True
                            top_key.clear()
                    elif b == 0x7B or b == 0x5B:       # { or [
                        depth += 1
                        if depth == 2:
                            entry_start = base + i
                            cur_key = bytes(top_key)
                            sample.clear()
                    elif b == 0x7D or b == 0x5D:       # } or ]
                        depth -= 1
                        if depth == 1 and entry_start is not None:
                            end = base + i + 1
                            m = AT_RE.search(bytes(sample))
                            ts = float(m.group(1)) if m else 0.0
                            entries.append((ts, entry_start, end, cur_key))
                            entry_start = None
                            if len(entries) >= want:
                                consumed = end
                                stop = True
                                break
                i += 1
            if stop:
                break
    return entries, consumed


def main():
    keep = 60
    dry = "--dry-run" in sys.argv
    for a in sys.argv[1:]:
        if a.startswith("--keep="):
            keep = int(a.split("=", 1)[1])
    head = int(keep * 1.5)

    size = os.path.getsize(TARGET)
    print(f"[trim] scanning head of {TARGET} ({size/1e6:.0f} MB) for {head} entries ...",
          flush=True)
    t0 = time.time()
    entries, consumed = scan_head(TARGET, head)
    print(f"[trim] scanned {consumed/1e6:.0f}MB, found {len(entries)} entries "
          f"in {time.time()-t0:.1f}s", flush=True)
    if not entries:
        raise SystemExit("[trim] ERROR: no entries parsed - file untouched")

    entries.sort(key=lambda e: e[0], reverse=True)
    kept = entries[:keep]
    print(f"[trim] keeping newest {len(kept)} (newest ts={kept[0][0]:.0f}, "
          f"oldest kept ts={kept[-1][0]:.0f})", flush=True)

    if dry:
        for ts, s, e, k in kept[:5]:
            print(f"        key={k.decode('utf8','replace')} ts={ts:.0f} span={e-s}B")
        print("[trim] dry-run - nothing written")
        return

    if not os.path.exists(BACKUP):
        print(f"[trim] backing up original -> {BACKUP}", flush=True)
        shutil.copyfile(TARGET, BACKUP)

    tmp = TARGET + ".tmp"
    with open(tmp, "wb") as out, open(TARGET, "rb") as src:
        out.write(b"{")
        first = True
        for ts, s, e, k in kept:
            src.seek(s)
            piece = src.read(e - s)
            if not first:
                out.write(b",")
            out.write(b'"' + k + b'":' + piece)
            first = False
        out.write(b"}")
    os.replace(tmp, TARGET)
    print(f"[trim] done: {size/1e6:.0f}MB -> {os.path.getsize(TARGET)/1e6:.1f}MB "
          f"({len(kept)} teams)", flush=True)


if __name__ == "__main__":
    main()
