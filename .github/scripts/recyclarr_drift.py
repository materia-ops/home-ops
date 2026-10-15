#!/usr/bin/env python3
"""Report TRaSH Guides changes that the recyclarr configs cannot pick up alone.

Guide-backed profiles already track TRaSH for scores, default CF groups and
default/required CFs. What needs a human decision is anything *optional* that
appears upstream: a new non-default CF group offered to one of our profiles,
or a new non-default CF inside a group we sync. This script lists everything
TRaSH currently offers each instance, diffs it against a reviewed baseline,
and prints a Markdown report of what is new. It also flags trash_ids our
configs reference that no longer exist, and selects that became redundant
because the guide promoted the CF to default/required.

Usage:
  recyclarr_drift.py [--trash DIR] [--out FILE|-]   report (default)
  recyclarr_drift.py [--trash DIR] --update-baseline  accept current upstream

Without --trash the TRaSH-Guides JSON is fetched with a shallow sparse git
clone. Needs PyYAML. Report-only: the exit status is 0 unless arguments or
inputs are bad; the report is empty when there is nothing to review.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
RECYCLARR_DIR = os.path.join(REPO_ROOT, "kubernetes", "apps", "media", "arr-apps", "recyclarr")
CONFIG_DIR = os.path.join(RECYCLARR_DIR, "app", "config")
BASELINE_FILE = os.path.join(RECYCLARR_DIR, "drift-baseline.json")
TRASH_REPO = "https://github.com/TRaSH-Guides/Guides.git"
MARKER = "<!-- recyclarr-drift -->"


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!env_var", lambda loader, node: None)
_Loader.add_constructor("!secret", lambda loader, node: None)


def is_true(value):
    return value is True or str(value).lower() == "true"


# --------------------------------------------------------------------------
# inputs

def fetch_trash(dest):
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none",
                    "--sparse", TRASH_REPO, dest], check=True)
    subprocess.run(["git", "-C", dest, "sparse-checkout", "set", "docs/json"], check=True)
    sha = subprocess.run(["git", "-C", dest, "rev-parse", "--short", "HEAD"],
                         check=True, capture_output=True, text=True).stdout.strip()
    return sha


def load_guide(trash_dir, app):
    base = os.path.join(trash_dir, "docs", "json", app)
    groups, cfs, profiles = {}, {}, set()
    for path in glob.glob(os.path.join(base, "quality-profiles", "*.json")):
        with open(path, encoding="utf-8") as f:
            profiles.add(json.load(f)["trash_id"])
    for path in glob.glob(os.path.join(base, "cf-groups", "*.json")):
        with open(path, encoding="utf-8") as f:
            g = json.load(f)
        groups[g["trash_id"]] = g
    for path in glob.glob(os.path.join(base, "cf", "*.json")):
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        cfs[c["trash_id"]] = c["name"]
    return groups, cfs, profiles


def load_instances(config_dir):
    """Yield (app, instance, config) for every instance in every config file."""
    for path in sorted(glob.glob(os.path.join(config_dir, "*.yaml"))):
        with open(path, encoding="utf-8") as f:
            doc = yaml.load(f, Loader=_Loader) or {}
        for app in ("radarr", "sonarr"):
            for name, cfg in (doc.get(app) or {}).items():
                yield app, name, cfg or {}


# --------------------------------------------------------------------------
# model

def offered(cfg, groups):
    """Everything TRaSH offers this instance: {group_id: {...}} for groups whose
    compatibility list includes one of our guide-backed profiles."""
    profiles = {p["trash_id"] for p in cfg.get("quality_profiles") or [] if p.get("trash_id")}
    cg = cfg.get("custom_format_groups") or {}
    added = {a["trash_id"] for a in cg.get("add") or []}
    skipped = set(cg.get("skip") or [])
    out = {}
    for gid, g in groups.items():
        include = set(((g.get("quality_profiles") or {}).get("include") or {}).values())
        if not profiles & include:
            continue
        default = is_true(g.get("default"))
        synced = gid in added or (default and gid not in skipped)
        out[gid] = {
            "name": g["name"],
            "default": default,
            "synced": synced,
            # only CFs we could still decide on: required ones always sync
            "cfs": {c["trash_id"]: {"name": c["name"], "default": is_true(c.get("default"))}
                    for c in g["custom_formats"] if not is_true(c.get("required"))},
        }
    return out


def snapshot(offer):
    """The baseline shape: names only, so the committed JSON diffs readably."""
    return {
        "groups": {gid: g["name"] for gid, g in sorted(offer.items())},
        "cfs": {gid: {cid: c["name"] for cid, c in sorted(g["cfs"].items())}
                for gid, g in sorted(offer.items()) if g["synced"]},
    }


def config_problems(cfg, groups, cfs, profiles):
    """Stale references and selects the guide has since made redundant."""
    problems = []
    cg = cfg.get("custom_format_groups") or {}
    for entry in cg.get("add") or []:
        gid = entry["trash_id"]
        g = groups.get(gid)
        if g is None:
            problems.append(f"`custom_format_groups.add` references unknown group `{gid}`")
            continue
        members = {c["trash_id"]: c for c in g["custom_formats"]}
        for cid in entry.get("select") or []:
            c = members.get(cid)
            if c is None:
                problems.append(f"{g['name']}: selected CF `{cid}` is no longer in the group")
            elif is_true(c.get("required")) or is_true(c.get("default")):
                kind = "required" if is_true(c.get("required")) else "default"
                problems.append(f"{g['name']}: selected CF {c['name']} is now {kind} "
                                "(the select is redundant; drop it)")
        for cid in entry.get("exclude") or []:
            if cid not in members:
                problems.append(f"{g['name']}: excluded CF `{cid}` is no longer in the group")
    for gid in cg.get("skip") or []:
        if gid not in groups:
            problems.append(f"`custom_format_groups.skip` references unknown group `{gid}`")
    for p in cfg.get("quality_profiles") or []:
        if p.get("trash_id") and p["trash_id"] not in profiles:
            problems.append(f"quality profile `{p['trash_id']}` no longer exists upstream")
    for block in cfg.get("custom_formats") or []:
        for cid in block.get("trash_ids") or []:
            if cid not in cfs:
                problems.append(f"`custom_formats` references unknown CF `{cid}`")
    return problems


def new_items(offer, base):
    """Human-readable lines for what upstream offers now but the baseline lacks."""
    lines = []
    seen_groups = (base or {}).get("groups", {})
    seen_cfs = (base or {}).get("cfs", {})
    for gid, g in sorted(offer.items(), key=lambda kv: kv[1]["name"]):
        if gid not in seen_groups:
            kind = "default" if g["default"] else "optional"
            if g["synced"]:
                lines.append(f"New {kind} group **{g['name']}** (`{gid}`): already syncing")
            elif g["default"]:
                lines.append(f"New default group **{g['name']}** (`{gid}`): skipped by config")
            else:
                lines.append(f"New optional group **{g['name']}** (`{gid}`): decide whether to `add` it")
            continue
        if not g["synced"]:
            continue
        known = seen_cfs.get(gid)
        if known is None:
            continue  # group newly synced by our own config change; nothing upstream
        for cid, c in sorted(g["cfs"].items(), key=lambda kv: kv[1]["name"]):
            if cid in known:
                continue
            if c["default"]:
                lines.append(f"{g['name']}: new default CF **{c['name']}** (`{cid}`): already "
                             "syncing; `exclude` it if unwanted")
            else:
                lines.append(f"{g['name']}: new optional CF **{c['name']}** (`{cid}`): decide "
                             "whether to `select` it")
    return lines


# --------------------------------------------------------------------------
# main

def run(trash_dir, config_dir, baseline_file, update, trash_ref):
    guides = {app: load_guide(trash_dir, app) for app in ("radarr", "sonarr")}
    try:
        with open(baseline_file, encoding="utf-8") as f:
            baseline = json.load(f)
    except FileNotFoundError:
        baseline = {}
    current, sections = {}, []
    for app, name, cfg in load_instances(config_dir):
        groups, cfs, profiles = guides[app]
        offer = offered(cfg, groups)
        key = f"{app}/{name}"
        current[key] = snapshot(offer)
        problems = config_problems(cfg, groups, cfs, profiles)
        news = new_items(offer, baseline.get("instances", {}).get(key))
        if problems or news:
            body = [f"### {key}"]
            body += [f"- :warning: {p}" for p in problems]
            body += [f"- {n}" for n in news]
            sections.append("\n".join(body))
    if update:
        with open(baseline_file, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"trash_ref": trash_ref, "instances": current}, f, indent=2, sort_keys=True)
            f.write("\n")
        return ""
    if not sections:
        return ""
    head = (f"{MARKER}\nTRaSH Guides offers items the recyclarr configs have not reviewed yet "
            f"(guide `{trash_ref}`, baseline `{baseline.get('trash_ref', 'none')}`).\n\n"
            "Decide each one in `kubernetes/apps/media/arr-apps/recyclarr/app/config/`, then "
            "accept the rest with `python3 .github/scripts/recyclarr_drift.py --update-baseline` "
            "and commit both. :warning: lines are config problems and need a config fix.\n")
    return head + "\n" + "\n\n".join(sections) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trash", help="TRaSH-Guides checkout (default: shallow clone)")
    ap.add_argument("--config-dir", default=CONFIG_DIR)
    ap.add_argument("--baseline", default=BASELINE_FILE)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--out", default="-")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        if args.trash:
            trash_dir = args.trash
            trash_ref = subprocess.run(["git", "-C", trash_dir, "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True).stdout.strip() or "local"
        else:
            trash_dir = os.path.join(tmp, "trash")
            trash_ref = fetch_trash(trash_dir)
        report = run(trash_dir, args.config_dir, args.baseline, args.update_baseline, trash_ref)
    if args.out == "-":
        sys.stdout.write(report)
    else:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
