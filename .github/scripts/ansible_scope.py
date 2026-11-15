#!/usr/bin/env python3
"""Turn the paths a push changed into the --tags and --limit its Ansible run needs.

Only paths that can change a host count: infrastructure/ minus Markdown, plus
talos/nodes/ (node IPs feed the pihole role) and any file in a role (a role can
ship Markdown to a host). path_scope() maps each to (tags, hosts); a run's scope
is the union, and ALL in either slot wins, so an unrecognised path widens the
run instead of being skipped.

Prints tags=<csv> and limit=<csv>; blank means everything.
Stdlib only, like ansible_last_applied.py.
"""
import argparse
import re
import sys

ALL = None

# The play tags each role runs under; a role several plays include has several.
ROLE_TAGS = {
    "dnscrypt_proxy": ("dnscrypt",),
    "ext4_metrics": ("observability", "pikvm"),
    "network": ("network",),
    "pihole": ("pihole",),
    "pikvm": ("pikvm",),
    "unattended_upgrades": ("unattended_upgrades",),
}


def counts(path):
    """Whether a changed path can affect a host."""
    if path.startswith(("talos/nodes/", "infrastructure/roles/")):
        return True
    return path.startswith("infrastructure/") and not path.endswith(".md")


def inventory_hosts(text):
    """Host names in an Ansible YAML inventory: the keys directly under `hosts:`."""
    hosts, indent = set(), None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        depth = len(line) - len(line.lstrip(" "))
        if indent is not None and depth <= indent:
            indent = None
        if indent is None:
            if stripped == "hosts:":
                indent = depth
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.-]+):(\s.*)?", stripped)
        if m and depth == indent + 2:
            hosts.add(m.group(1))
    return hosts


def path_scope(path, known_hosts):
    """(tags, hosts) one counted path needs; ALL in a slot means everything."""
    if path.startswith("talos/nodes/"):
        return {"pihole"}, ALL
    m = re.fullmatch(r"infrastructure/roles/([^/]+)/.+", path)
    if m and m.group(1) in ROLE_TAGS:
        return set(ROLE_TAGS[m.group(1)]), ALL
    if path.startswith("infrastructure/inventory/group_vars/"):
        return {"observability"}, ALL
    m = re.fullmatch(r"infrastructure/inventory/host_vars/([^/]+)\.ya?ml", path)
    if m and m.group(1) in known_hosts:
        return ALL, {m.group(1)}
    return ALL, ALL


def scope(paths, known_hosts):
    """(tags, limit) strings for a run covering every counted path; '' = everything."""
    counted = [p for p in paths if counts(p)]
    if not counted:
        return "", ""
    tags, hosts = set(), set()
    for path in counted:
        t, h = path_scope(path, known_hosts)
        tags = ALL if tags is ALL or t is ALL else tags | t
        hosts = ALL if hosts is ALL or h is ALL else hosts | h
    return (
        "" if tags is ALL else ",".join(sorted(tags)),
        "" if hosts is ALL else ",".join(sorted(hosts)),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", required=True, help="changed paths, one per line")
    parser.add_argument("--inventory", required=True, help="infrastructure/inventory/hosts.yaml")
    args = parser.parse_args()

    with open(args.files, encoding="utf-8") as fh:
        paths = [line.strip() for line in fh if line.strip()]
    with open(args.inventory, encoding="utf-8") as fh:
        known = inventory_hosts(fh.read())

    tags, limit = scope(paths, known)
    print(f"tags={tags}")
    print(f"limit={limit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
