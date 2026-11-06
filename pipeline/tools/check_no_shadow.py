#!/usr/bin/env python3
"""Fail if any .py file in pipeline/ shadows a Python stdlib module.

Running a module as `python3 -m pipeline.render.voice` puts the repo
root at the front of sys.path, so a local file named e.g. queue.py
silently replaces the stdlib `queue` module for every import in that
process. That broke the voice job once: torch does `from queue import
Queue` and got our queue helper instead. This check runs first in the
draft and render jobs so a bad filename can never silently break a run
again. It walks the whole pipeline/ tree, not just one directory.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    bad = []
    for dirpath, _dirs, files in os.walk(ROOT):
        for name in sorted(files):
            if name.endswith(".py"):
                mod = name[:-3]
                if mod in sys.stdlib_module_names:
                    bad.append(os.path.relpath(
                        os.path.join(dirpath, name),
                        os.path.dirname(ROOT)))
    if bad:
        print("error: these files shadow stdlib modules: " + ", ".join(bad),
              file=sys.stderr)
        print("rename them (e.g. queue.py -> drive_queue.py)", file=sys.stderr)
        return 1
    print("no stdlib shadowing in pipeline/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
