#!/usr/bin/env python3
"""Fetch the failed jobs' logs for a workflow run and extract the error.

`gh run view --log-failed` returns nothing for a run that is still in
progress (the repair job is part of that same run), so the repair job
could not see the error. This script uses the GitHub API directly:
list the run's jobs, find the failed ones, and download each failed
job's log via the logs endpoint. That endpoint answers with a 302
redirect to a temporary blob URL; the blob rejects the Authorization
header, so this follows the redirect WITHOUT auth headers (the same
pattern as the local log helper).

Usage: fetch_failed_log.py --run-id N --repo OWNER/REPO --out error.txt
Env: GH_TOKEN (or GITHUB_TOKEN) with actions:read.
Stdlib only.
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def api_get(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "quiet-ledger-repair",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_log(url, token):
    """Fetch one job's log. Two hops, different auth:
    - Hop 1, the GitHub API logs endpoint: REQUIRES the token, or it
      answers 403 even for a public repo.
    - Hop 2, the temporary blob URL from the 302 Location: the blob
      REJECTS the Authorization header, so fetch it without auth.
    The earlier version sent no auth on hop 1, so every repair 403'd."""
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "quiet-ledger-repair",
    })
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=120) as resp:
            return resp.read().decode("utf-8", "replace")
    except RedirectError as e:
        location = e.location
        req2 = urllib.request.Request(
            location, headers={"User-Agent": "quiet-ledger-repair"})
        with urllib.request.urlopen(req2, timeout=120) as resp:
            return resp.read().decode("utf-8", "replace")


class RedirectError(Exception):
    def __init__(self, location):
        super().__init__(f"redirect to {location}")
        self.location = location


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectError(newurl)


def extract_error(log_text, max_lines=150):
    """Take the tail of the log; the failure is at the end."""
    lines = log_text.splitlines()
    return "\n".join(lines[-max_lines:])


def main():
    parser = argparse.ArgumentParser(description="fetch failed job logs")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("need GH_TOKEN or GITHUB_TOKEN", file=sys.stderr)
        return 2
    api = f"https://api.github.com/repos/{args.repo}/actions"
    jobs = api_get(f"{api}/runs/{args.run_id}/jobs?per_page=50", token)["jobs"]
    failed = [j for j in jobs if j.get("conclusion") == "failure"]
    if not failed:
        print("no failed jobs in this run", file=sys.stderr)
        return 1
    parts = []
    for job in failed:
        print(f"fetching log for failed job: {job['name']}", flush=True)
        try:
            log = fetch_log(
                f"{api}/jobs/{job['id']}/logs", token)
        except Exception as e:  # noqa: BLE001
            print(f"  could not fetch log for {job['name']}: {e}",
                  file=sys.stderr)
            continue
        parts.append(f"=== job: {job['name']} ===\n" + extract_error(log))
    if not parts:
        print("could not fetch any failed job log", file=sys.stderr)
        return 1
    text = "\n\n".join(parts)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {args.out}: {len(text.splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
