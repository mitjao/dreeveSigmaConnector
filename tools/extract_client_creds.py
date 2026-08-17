#!/usr/bin/env python3
"""
extract_client_creds.py — Read the SIGMA app's OAuth client_id / client_secret
out of *your own* SIGMA DATA CENTER installation.

Why this is needed: SIGMA Cloud has no public API. Its official desktop app
authenticates with an OAuth "password grant" using a client_id/client_secret
that ship embedded in the app binary (constants CLIENT_ID_MAC / CLIENT_SECRET_MAC
etc. inside Contents/Resources/CloudWorker.swf). To talk to your own cloud
account programmatically we reuse those same two values — the same way the
Garmin/Polar Dreeve connectors reuse each vendor's app endpoints.

This runs entirely on your machine, reads only files you already own, and sends
nothing anywhere. You run it; you decide what to do with the output.

Usage:
  # point it at the mounted .app or the .swf directly:
  python3 extract_client_creds.py "/Applications/SIGMA DataCenter.app"
  python3 extract_client_creds.py /path/to/CloudWorker.swf

It prints the strings surrounding each CLIENT_ID_* / CLIENT_SECRET_* constant so
you can read off the values. OAuth client ids are usually short slugs; secrets
are longer random-looking tokens.
"""

import os
import re
import sys
import zlib


def find_swf(path):
    if path.endswith(".swf"):
        return path
    # An .app bundle or a directory: look for CloudWorker.swf inside it.
    for root, _dirs, files in os.walk(path):
        for name in files:
            if name.lower() == "cloudworker.swf":
                return os.path.join(root, name)
    sys.exit(f"CloudWorker.swf not found under {path!r}")


def decompress_swf(swf_path):
    raw = open(swf_path, "rb").read()
    sig = raw[:3]
    if sig == b"FWS":
        return raw  # uncompressed
    if sig == b"CWS":  # zlib
        return b"FWS" + raw[3:8] + zlib.decompress(raw[8:])
    if sig == b"ZWS":
        sys.exit("SWF is LZMA-compressed; install `pip install pylzma` or ask for help.")
    sys.exit(f"Not an SWF: {swf_path!r}")


def extract_strings(data, minlen=3):
    """Yield (offset, string) for printable ASCII runs — like `strings`."""
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, data):
        yield m.start(), m.group().decode("ascii", "replace")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    swf = find_swf(sys.argv[1])
    print(f"# SWF: {swf}")
    data = decompress_swf(swf)
    print(f"# decompressed size: {len(data)} bytes\n")

    strings = list(extract_strings(data))
    idx = {s: i for i, (_off, s) in enumerate(strings)}

    labels = [
        "CLIENT_ID_MAC", "CLIENT_SECRET_MAC",
        "CLIENT_ID_WINDOWS", "CLIENT_SECRET_WINDOWS",
        "CLIENT_ID_IOS", "CLIENT_SECRET_IOS",
        "CLIENT_ID_ANDROID", "CLIENT_SECRET_ANDROID",
    ]

    for label in labels:
        i = idx.get(label)
        if i is None:
            print(f"## {label}: (not found)")
            continue
        print(f"## {label}: found at string #{i}")
        lo, hi = max(0, i - 4), min(len(strings), i + 6)
        for j in range(lo, hi):
            off, s = strings[j]
            mark = " <-- label" if j == i else ""
            preview = s if len(s) <= 80 else s[:77] + "..."
            print(f"    [{j}] {preview!r}{mark}")
        print()

    print("# The value for each constant is one of the nearby strings above")
    print("# (typically the short slug next to CLIENT_ID_*, and the longer")
    print("# random token next to CLIENT_SECRET_*). If it's ambiguous, paste")
    print("# the blocks back and we'll pick them out together.")


if __name__ == "__main__":
    main()
