#!/usr/bin/env python3
"""Find the commit the last successful Ansible push run on main applied.

ansible.yaml runs Check + Apply in one concurrency group, and GitHub cancels a
pending job there when a third run arrives. A run therefore has to cover every
change since the last push run on main that succeeded (success means its Apply
ran), not just since github.event.before: cancelled and failed runs in between
are folded into it.

Prints key=value lines:
  base=<sha>      head of the last successful push run, empty if none
  status=<s>      compare status of base...SHA: ahead, behind, identical,
                  diverged, or none when there is no base
  complete=<b>    false when the changed-file list hit the API's 300-file cap
With --files PATH it also writes the changed paths there, one per line.

Env: GH_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_WORKFLOW_REF, SHA.
Stdlib only: it runs on ubuntu-latest and in the Ansible job image. Any API
error exits non-zero; callers decide whether that fails open or closed.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.github.com"
COMPARE_FILE_CAP = 300


def workflow_file(workflow_ref):
    """owner/repo/.github/workflows/x.yaml@refs/heads/b -> x.yaml"""
    return workflow_ref.split("@", 1)[0].rsplit("/", 1)[-1]


def last_applied(runs, current_run_id):
    """Head SHA of the newest run that is not this one (reruns keep their id)."""
    for run in runs:
        if str(run["id"]) != str(current_run_id):
            return run["head_sha"]
    return ""


def get(path, token):
    req = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", help="write the changed paths to this file")
    args = parser.parse_args()

    env = os.environ
    token, repo, sha = env["GH_TOKEN"], env["GITHUB_REPOSITORY"], env["SHA"]
    query = urllib.parse.urlencode(
        {"branch": "main", "event": "push", "status": "success", "per_page": 5}
    )
    wf = urllib.parse.quote(workflow_file(env["GITHUB_WORKFLOW_REF"]))
    runs = get(f"/repos/{repo}/actions/workflows/{wf}/runs?{query}", token)
    base = last_applied(runs.get("workflow_runs", []), env["GITHUB_RUN_ID"])

    status, files = "none", []
    if base:
        cmp = get(f"/repos/{repo}/compare/{base}...{sha}", token)
        status = cmp["status"]
        files = [f["filename"] for f in cmp.get("files", [])]
    if args.files:
        with open(args.files, "w", encoding="utf-8") as fh:
            fh.write("".join(f"{name}\n" for name in files))

    print(f"base={base}")
    print(f"status={status}")
    print(f"complete={'true' if len(files) < COMPARE_FILE_CAP else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
