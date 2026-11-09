#!/usr/bin/env python3
"""Dispatch the echoes-render workflow on GitHub (Hub use).

Usage:
    python3 scripts/dispatch_echoes_render.py \
        --video-id 79 \
        --drive-folder-id <staging folder id in quiet-ledger> \
        --video-title "The Antikythera Mechanism" \
        --final-name 79-antikythera-test-v1

This calls the GitHub API with the fine-grained PAT registered as
custom.github-pat (see ~/workspace/custom-connectors/custom.github-pat/
CONNECTOR.md). It never handles a secret itself: the workflow's Drive
secrets (DRIVE_OAUTH_JSON, DRIVE_FOLDER_ID) live in the repo's
Actions secrets and are read by the workflow, not by this script.

The dispatch is manual-only by design: the Hub dispatches after the
per-video side chat has locked the clips and put them in the staging
folder, and after the Hub has checked the staging folder contents.
After dispatch, watch the run at
https://github.com/SaNtOsH6099/quiet-ledger/actions/workflows/echoes-render.yml
"""
import argparse
import json
import subprocess
import sys

API = ["python3",
       "/home/hatch/workspace/custom-connectors/custom.github-pat/bin/github_api.py"]
OWNER, REPO = "SaNtOsH6099", "quiet-ledger"


def gh(method, path, body=None):
    cmd = API + [method, path]
    if body is not None:
        cmd.append(json.dumps(body))
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        # A workflow_dispatch answers 204 No Content (empty body),
        # which github_api.py cannot parse as JSON and reports as a
        # failure — but the dispatch itself succeeded. Treat an empty
        # body on a dispatch as success; verify with the runs list.
        if "provider response was not valid JSON" in out.stderr \
                and not out.stdout.strip():
            return {}
        print(out.stdout, file=sys.stderr)
        print(out.stderr, file=sys.stderr)
        raise SystemExit(f"github_api {method} {path} failed "
                         f"(exit {out.returncode})")
    return json.loads(out.stdout) if out.stdout.strip() else {}


def main():
    parser = argparse.ArgumentParser(
        description="dispatch echoes-render on GitHub")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--drive-folder-id", required=True)
    parser.add_argument("--video-title", required=True)
    parser.add_argument("--final-name", required=True,
                        help="final filename without extension, "
                             "e.g. 79-antikythera-test-v1")
    args = parser.parse_args()

    res = gh("POST",
             f"/repos/{OWNER}/{REPO}/actions/workflows/echoes-render.yml/dispatches",
             {"ref": "main",
              "inputs": {"video_id": args.video_id,
                         "drive_folder_id": args.drive_folder_id,
                         "video_title": args.video_title,
                         "final_name": args.final_name}})
    print("dispatched echoes-render on main:", res or "OK")
    print("watch: https://github.com/SaNtOsH6099/quiet-ledger/"
          "actions/workflows/echoes-render.yml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
