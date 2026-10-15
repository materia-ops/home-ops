#!/usr/bin/env python3
"""Report TRaSH Guides changes to review in the recyclarr configs.

Guide-backed profiles already track TRaSH for scores, default CF groups and
default/required CFs, so most upstream changes reach the cluster on the next
sync without a config edit. This script makes those silent changes visible
and lists the ones that need a decision:

- new optional CF groups offered to one of our profiles, and new optional CFs
  inside a group we sync (decide whether to add/select them);
- default flips: a group or CF that became default (now syncing) or stopped
  being default (stopped syncing unless the config adds/selects it);
- groups and CFs that disappeared upstream;
- config problems: trash_ids that no longer exist, selects the guide has made
  redundant, and a baseline older than the configs.

It lists everything TRaSH currently offers each instance, diffs that against
the reviewed baseline, and prints a Markdown report (empty when clean).

Usage:
  recyclarr_drift.py [--trash DIR] [--out FILE|-]    report (default)
  recyclarr_drift.py [--trash DIR] --update-baseline  accept current upstream

Without --trash the TRaSH-Guides JSON is fetched with a shallow sparse git
clone. Needs PyYAML. Report-only: the exit status is 0 unless arguments or
inputs are bad.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships on ubuntu-latest
    yaml = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
RECYCLARR_DIR = os.path.join(REPO_ROOT, "kubernetes", "apps", "media", "arr-apps", "recyclarr")
CONFIG_DIR = os.path.join(RECYCLARR_DIR, "app", "config")
BASELINE_FILE = os.path.join(RECYCLARR_DIR, "drift-baseline.json")
TRASH_REPO = "https://github.com/TRaSH-Guides/Guides.git"
MARKER = "<!-- recyclarr-drift -->"


def is_true(value):
    return value is True or str(value).lower() == "true"


def code(text):
    """Upstream names are third-party text: render them inert in the issue."""
    return "`" + str(text).replace("`", "'") + "`"


# --------------------------------------------------------------------------
# inputs

def fetch_trash(dest):
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none",
                    "--sparse", TRASH_REPO, dest], check=True)
    subprocess.run(["git", "-C", dest, "sparse-checkout", "set", "docs/json"], check=True)
    return subprocess.run(["git", "-C", dest, "rev-parse", "--short", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def load_guide(trash_dir, app):
    base = os.path.join(trash_dir, "docs", "json", app)

    def each(sub):
        for path in glob.glob(os.path.join(base, sub, "*.json")):
            with open(path, encoding="utf-8") as f:
                yield json.load(f)

    profiles = {p["trash_id"] for p in each("quality-profiles")}
    groups = {g["trash_id"]: g for g in each("cf-groups")}
    cfs = {c["trash_id"]: c["name"] for c in each("cf")}
    return groups, cfs, profiles


def load_instances(config_dir):
    """Yield (app, instance, config) for every instance in every config file."""
    if yaml is None:
        raise SystemExit("recyclarr_drift.py needs PyYAML")

    class Loader(yaml.SafeLoader):
        pass

    for tag in ("!env_var", "!secret"):
        Loader.add_constructor(tag, lambda loader, node: None)
    for path in sorted(glob.glob(os.path.join(config_dir, "*.yaml"))):
        with open(path, encoding="utf-8") as f:
            doc = yaml.load(f, Loader=Loader) or {}
        for app in ("radarr", "sonarr"):
            for name, cfg in (doc.get(app) or {}).items():
                yield app, name, cfg or {}


# --------------------------------------------------------------------------
# model

def offered(cfg, groups):
    """Everything TRaSH offers this instance, keyed by group trash_id: groups whose
    compatibility list includes one of our guide-backed profiles."""
    profiles = {p["trash_id"] for p in cfg.get("quality_profiles") or [] if p.get("trash_id")}
    cg = cfg.get("custom_format_groups") or {}
    adds = {a["trash_id"]: a for a in cg.get("add") or []}
    skipped = set(cg.get("skip") or [])
    out = {}
    for gid, g in groups.items():
        include = set(((g.get("quality_profiles") or {}).get("include") or {}).values())
        if not profiles & include:
            continue
        default = is_true(g.get("default"))
        entry = adds.get(gid, {})
        out[gid] = {
            "name": g["name"],
            "default": default,
            "synced": gid in adds or (default and gid not in skipped),
            "select": set(entry.get("select") or []),
            "select_all": bool(entry.get("select_all")),
            "exclude": set(entry.get("exclude") or []),
            # required CFs always sync, so only the rest are choices
            "cfs": {c["trash_id"]: {"name": c["name"], "default": is_true(c.get("default"))}
                    for c in g["custom_formats"] if not is_true(c.get("required"))},
        }
    return out


def snapshot(offer):
    """The committed baseline: every offered group and every CF choice in the
    groups we sync, with the default flags so flips can be detected."""
    return {
        "groups": {gid: {"name": g["name"], "default": g["default"]}
                   for gid, g in sorted(offer.items())},
        "cfs": {gid: {cid: {"name": c["name"], "default": c["default"]}
                      for cid, c in sorted(g["cfs"].items())}
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
                problems.append(f"{code(g['name'])}: selected CF `{cid}` is no longer in the group")
            elif is_true(c.get("required")) or is_true(c.get("default")):
                kind = "required" if is_true(c.get("required")) else "default"
                problems.append(f"{code(g['name'])}: selected CF {code(c['name'])} is now {kind} "
                                "(the select is redundant; drop it)")
        for cid in entry.get("exclude") or []:
            if cid not in members:
                problems.append(f"{code(g['name'])}: excluded CF `{cid}` is no longer in the group")
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


def cf_syncs(g, cid, default):
    if cid in g["exclude"]:
        return False
    return default or cid in g["select"] or g["select_all"]


def changes(offer, base):
    """(stale, lines): whether the baseline predates the configs, and one line
    per upstream change since the baseline."""
    seen_groups = (base or {}).get("groups", {})
    seen_cfs = (base or {}).get("cfs", {})
    stale, lines = False, []
    for gid, g in sorted(offer.items(), key=lambda kv: kv[1]["name"]):
        name = code(g["name"])
        was = seen_groups.get(gid)
        if was is None:
            if g["synced"]:
                kind = "default" if g["default"] else "optional"
                lines.append(f"New {kind} group {name} (`{gid}`): already syncing")
            elif g["default"]:
                lines.append(f"New default group {name} (`{gid}`): skipped by config")
            else:
                lines.append(f"New optional group {name} (`{gid}`): decide whether to `add` it")
            continue
        if was["default"] != g["default"]:
            if g["default"]:
                state = "already syncing" if g["synced"] else "skipped by config"
                lines.append(f"Group {name} is now default: {state}")
            elif not g["synced"]:
                lines.append(f"Group {name} is no longer default: stopped syncing; `add` it to keep it")
        if not g["synced"]:
            continue
        known = seen_cfs.get(gid)
        if known is None:
            stale = True  # synced since the baseline was taken: a config change
            continue
        for cid, c in sorted(g["cfs"].items(), key=lambda kv: kv[1]["name"]):
            cname = code(c["name"])
            prior = known.get(cid)
            if prior is None:
                if cf_syncs(g, cid, c["default"]):
                    kind = "default" if c["default"] else "optional (via select_all)"
                    lines.append(f"{name}: new {kind} CF {cname} (`{cid}`): already syncing; "
                                 "`exclude` it if unwanted")
                else:
                    lines.append(f"{name}: new optional CF {cname} (`{cid}`): decide whether to "
                                 "`select` it")
            elif prior["default"] != c["default"]:
                if cf_syncs(g, cid, c["default"]) != cf_syncs(g, cid, prior["default"]):
                    if c["default"]:
                        lines.append(f"{name}: CF {cname} is now default: started syncing")
                    else:
                        lines.append(f"{name}: CF {cname} is no longer default: stopped syncing; "
                                     "`select` it to keep it")
        for cid in sorted(set(known) - set(g["cfs"])):
            lines.append(f"{name}: CF {code(known[cid]['name'])} (`{cid}`) left the group "
                         "or became required")
    for gid in sorted(set(seen_groups) - set(offer)):
        lines.append(f"Group {code(seen_groups[gid]['name'])} (`{gid}`) is no longer offered to "
                     "this profile (removed upstream or dropped from its compatibility list)")
    return stale, lines


# --------------------------------------------------------------------------
# main

def run(trash_dir, config_dir, baseline_file, update, trash_ref):
    guides = {app: load_guide(trash_dir, app) for app in ("radarr", "sonarr")}
    baseline = {}
    if not update:  # accepting must not depend on the old baseline's shape
        try:
            with open(baseline_file, encoding="utf-8") as f:
                baseline = json.load(f)
        except FileNotFoundError:
            pass
    current, sections = {}, []
    for app, name, cfg in load_instances(config_dir):
        groups, cfs, profiles = guides[app]
        offer = offered(cfg, groups)
        key = f"{app}/{name}"
        current[key] = snapshot(offer)
        problems = config_problems(cfg, groups, cfs, profiles)
        stale, lines = changes(offer, baseline.get("instances", {}).get(key))
        if stale:
            problems.append("the baseline predates a config change (a newly synced group has no "
                            "recorded CFs): run `--update-baseline`")
        if problems or lines:
            body = [f"### {key}"]
            body += [f"- :warning: {p}" for p in problems]
            body += [f"- {line}" for line in lines]
            sections.append("\n".join(body))
    if update:
        with open(baseline_file, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"trash_ref": trash_ref, "instances": current}, f, indent=2, sort_keys=True)
            f.write("\n")
        return ""
    if not sections:
        return ""
    head = (f"{MARKER}\nTRaSH Guides changes since the reviewed recyclarr baseline "
            f"(guide `{trash_ref}`, baseline `{baseline.get('trash_ref', 'none')}`).\n\n"
            "Decide each item in `kubernetes/apps/media/arr-apps/recyclarr/app/config/`, then "
            "accept the rest with `python3 .github/scripts/recyclarr_drift.py --update-baseline` "
            "and commit both. Lines marked :warning: are config problems that need a config fix.\n")
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
