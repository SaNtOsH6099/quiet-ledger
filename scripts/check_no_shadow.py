#!/usr/bin/env python3
"""Fail if any .py file in scripts/ shadows a Python stdlib module.

Running a script as `python3 scripts/voice.py` puts scripts/ at the
front of sys.path, so a local file named e.g. queue.py silently replaces
the stdlib `queue` module for every import in that process. That broke
the voice job: torch does `from queue import Queue` and got our queue
helper instead. This check runs first in the draft and render jobs so
a bad filename can never silently break a run again.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    bad = []
    for name in sorted(os.listdir(HERE)):
        if name.endswith(".py"):
            mod = name[:-3]
            if mod in sys.stdlib_module_names:
                bad.append(name)
    if bad:
        print("error: these files shadow stdlib modules: " + ", ".join(bad),
              file=sys.stderr)
        print("rename them (e.g. queue.py -> drive_queue.py)", file=sys.stderr)
        return 1
    print("no stdlib shadowing in scripts/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
