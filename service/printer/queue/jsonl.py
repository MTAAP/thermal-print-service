from __future__ import annotations

import os
from pathlib import Path


def append_line(path: Path, line: str) -> None:
    data = (line + "\n").encode("utf-8")
    with open(path, "ab+") as f:
        # Power loss mid-append can leave a torn final line with no
        # newline. Writing straight after it would fuse both into one
        # unparseable line, and replay would drop this record too.
        # Terminate the fragment so only it is lost.
        if f.seek(0, os.SEEK_END) > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                data = b"\n" + data
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
