#!/usr/bin/env python3
"""Report manifests whose CRD apiVersion lags what the cluster publishes.

crd-schema-publisher publishes the live cluster's CRD schemas to
https://schemas.materia.wtf; its all.json lists every apiVersion/kind pair.
This script collects every apiVersion/kind pair in kubernetes/ (top-level
documents, nested references such as Flux healthChecks, and YAML embedded in
string values such as inline patches) and reports:

- versions the cluster does not publish for that kind (already removed, or a
  change that adds them has not reconciled yet);
- kinds the cluster does not have at all (removed CRD, or a group move);
- versions older than the newest one published, by Kubernetes version
  priority: GA > beta > alpha, then the higher major, then the higher minor;
- allowlist entries that no longer match anything.

Reviewed exceptions live in api-version-drift-allow.yaml next to this script.
Kubernetes built-in groups and kustomize's own config kinds are skipped.

Usage:
  api_version_drift.py [--index FILE|URL] [--root DIR] [--allow FILE] [--out FILE|-]

Prints a Markdown report, empty when there is nothing to review, and a run
summary on stderr (and to $GITHUB_STEP_SUMMARY when set). Report-only: exit 0
with or without findings; exit 2 when the index cannot be fetched or parsed,
looks incomplete (a sentinel kind missing, or too few repo kinds found in it),
or the allowlist is malformed. Needs PyYAML.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships on ubuntu-latest
    yaml = None

HERE = pathlib.Path(__file__).resolve().parent
INDEX_URL = "https://schemas.materia.wtf/all.json"
MARKER = "<!-- api-version-drift -->"

GROUP_RE = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
KIND_RE = re.compile(r"[A-Z][A-Za-z0-9]*\Z")
VERSION_RE = re.compile(r"v([1-9][0-9]*)(?:(alpha|beta)([1-9][0-9]*))?\Z")

BUILTIN_GROUPS = frozenset({
    "admissionregistration.k8s.io",
    "apiextensions.k8s.io",
    "apiregistration.k8s.io",
    "apps",
    "authentication.k8s.io",
    "authorization.k8s.io",
    "autoscaling",
    "batch",
    "certificates.k8s.io",
    "coordination.k8s.io",
    "discovery.k8s.io",
    "events.k8s.io",
    "flowcontrol.apiserver.k8s.io",
    "internal.apiserver.k8s.io",
    "kustomize.config.k8s.io",
    "networking.k8s.io",
    "node.k8s.io",
    "policy",
    "rbac.authorization.k8s.io",
    "resource.k8s.io",
    "scheduling.k8s.io",
    "storage.k8s.io",
    "storagemigration.k8s.io",
})

# Present on every healthy publish; one missing means the index is partial.
SENTINELS = (
    ("external-secrets.io", "ExternalSecret"),
    ("helm.toolkit.fluxcd.io", "HelmRelease"),
    ("kustomize.toolkit.fluxcd.io", "Kustomization"),
)
MIN_COVERAGE = 0.9

TOP_API_RE = re.compile(r"^apiVersion:\s*[\"']?([^\s\"'#]+)", re.M)
TOP_KIND_RE = re.compile(r"^kind:\s*[\"']?([^\s\"'#]+)", re.M)
DOC_SPLIT_RE = re.compile(r"^---[^\n]*$", re.M)


class Problem(Exception):
    """Input that makes the report untrustworthy; exit 2."""


def rank(version):
    """Kubernetes version priority as a sortable tuple, or None if unparseable."""
    m = VERSION_RE.match(version)
    if not m:
        return None
    tier = {"alpha": 0, "beta": 1, None: 2}[m.group(2)]
    return (tier, int(m.group(1)), int(m.group(3) or 0))


def split_api_version(api_version):
    group, sep, version = api_version.rpartition("/")
    if not sep or not GROUP_RE.match(group) or rank(version) is None:
        return None
    return group, version



def load_index(source):
    if source.startswith("https://"):
        req = urllib.request.Request(source, headers={
            "Accept": "application/json",
            "User-Agent": "home-ops-api-version-drift",
        })
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    text = resp.read().decode("utf-8")
                break
            except OSError as exc:
                if attempt == 2:
                    raise Problem(f"fetching {source}: {exc}") from exc
                time.sleep(5)
    else:
        text = pathlib.Path(source).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError as exc:
        # The site answers unknown paths with an HTML page and status 200.
        raise Problem(f"{source} is not JSON: {exc}") from exc
    return parse_index(data)


def parse_index(data):
    """Return ({(group, kind): {version}}, rejected entry count)."""
    if not isinstance(data, dict) or not isinstance(data.get("oneOf"), list):
        raise Problem("index has no oneOf list")
    published, rejected = {}, 0
    for entry in data["oneOf"]:
        parts = entry.get("allOf", []) if isinstance(entry, dict) else []
        for part in parts:
            props = part.get("properties") if isinstance(part, dict) else None
            if not isinstance(props, dict):
                continue
            api_versions = (props.get("apiVersion") or {}).get("enum") or []
            kinds = (props.get("kind") or {}).get("enum") or []
            for api_version in api_versions:
                for kind in kinds:
                    split = split_api_version(api_version) if isinstance(api_version, str) else None
                    if split is None or not isinstance(kind, str) or not KIND_RE.match(kind):
                        rejected += 1
                        continue
                    published.setdefault((split[0], kind), set()).add(split[1])
    return published, rejected



if yaml is not None:
    class TolerantLoader(yaml.SafeLoader):
        """SafeLoader that ignores custom tags and allows redefined anchors."""

        def compose_node(self, parent, index):
            event = self.peek_event()
            if not isinstance(event, yaml.AliasEvent) and getattr(event, "anchor", None):
                self.anchors.pop(event.anchor, None)
            return super().compose_node(parent, index)

    TolerantLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def refs_in_text(text):
    """apiVersion/kind pairs in a YAML text, and whether the regex fallback ran."""
    found = []
    try:
        for doc in yaml.load_all(text, Loader=TolerantLoader):
            walk(doc, found)
        return found, False
    except yaml.YAMLError:
        for doc in DOC_SPLIT_RE.split(text):
            api_version, kind = TOP_API_RE.search(doc), TOP_KIND_RE.search(doc)
            if api_version and kind:
                found.append((api_version.group(1), kind.group(1)))
        return found, True


def walk(node, found):
    if isinstance(node, dict):
        api_version, kind = node.get("apiVersion"), node.get("kind")
        if isinstance(api_version, str) and isinstance(kind, str):
            found.append((api_version, kind))
        for value in node.values():
            walk(value, found)
    elif isinstance(node, list):
        for value in node:
            walk(value, found)
    elif isinstance(node, str) and "apiVersion:" in node and "kind:" in node:
        found.extend(refs_in_text(node)[0])


def scan(root):
    """Return ({(group, version, kind): {path}}, files scanned, fallback paths)."""
    uses, files, fallback = {}, 0, []
    base = root / "kubernetes"
    paths = sorted(p for p in base.rglob("*") if p.suffix in (".yaml", ".yml") and p.is_file())
    for path in paths:
        files += 1
        rel = path.relative_to(root).as_posix()
        found, fell_back = refs_in_text(path.read_text(encoding="utf-8"))
        if fell_back:
            fallback.append(rel)
        for api_version, kind in found:
            split = split_api_version(api_version)
            if split is None or not KIND_RE.match(kind):
                continue
            uses.setdefault((split[0], split[1], kind), set()).add(rel)
    return uses, files, fallback



def load_allow(path):
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    allow = {}
    for i, entry in enumerate(data.get("allow") or []):
        if not isinstance(entry, dict) or not all(
                isinstance(entry.get(k), str) and entry[k].strip()
                for k in ("apiVersion", "kind", "reason")):
            raise Problem(f"{path.name}: allow[{i}] needs apiVersion, kind and reason")
        split = split_api_version(entry["apiVersion"])
        if split is None or not KIND_RE.match(entry["kind"]):
            raise Problem(f"{path.name}: allow[{i}] has an invalid apiVersion or kind")
        allow[(split[0], split[1], entry["kind"])] = entry["reason"].strip()
    return allow



def classify(uses, published, allow):
    findings = {"unpublished": [], "unknown": [], "stale": []}
    suppressed, considered = [], set()
    for key in sorted(uses):
        group, version, kind = key
        if group in BUILTIN_GROUPS:
            continue
        considered.add((group, kind))
        versions = published.get((group, kind))
        if versions is None:
            row = ("unknown", key, None)
        elif version not in versions:
            row = ("unpublished", key, ", ".join(sorted(versions, key=rank, reverse=True)))
        else:
            newest = max(versions, key=rank)
            if rank(version) >= rank(newest):
                continue
            row = ("stale", key, newest)
        if key in allow:
            suppressed.append(key)
        else:
            findings[row[0]].append(row[1:])
    unused = sorted(k for k in allow if k not in suppressed)
    return findings, suppressed, unused, considered


def table(rows, uses, third):
    lines = [f"| apiVersion | Kind | {third} | Files |", "|---|---|---|---|"]
    for (group, version, kind), detail in rows:
        files = "<br>".join(f"`{p}`" for p in sorted(uses[(group, version, kind)]))
        lines.append(f"| `{group}/{version}` | {kind} | {detail or '-'} | {files} |")
    return lines


def render(findings, unused, uses):
    if not any(findings.values()) and not unused:
        return ""
    out = [MARKER,
           "Manifests whose apiVersion lags what the cluster publishes on "
           "[schemas.materia.wtf](https://schemas.materia.wtf/). Report-only, refreshed "
           "by `.github/workflows/api-version-drift.yaml`; accept a deliberate exception "
           "in `.github/scripts/api-version-drift-allow.yaml`.", ""]
    if findings["unpublished"]:
        out += ["### Version not published by the cluster", "",
                "Flux applies of these fail, unless the change that adds the version "
                "has not reconciled yet.", ""]
        out += table(findings["unpublished"], uses, "Cluster publishes") + [""]
    if findings["unknown"]:
        out += ["### Kind not on the cluster", "",
                "The CRD was removed or moved to another group.", ""]
        out += table(findings["unknown"], uses, "Cluster publishes") + [""]
    if findings["stale"]:
        out += ["### Newer version available", ""]
        out += table(findings["stale"], uses, "Newest") + [""]
    if unused:
        out += ["### Allowlist entries that no longer match", ""]
        out += [f"- `{g}/{v}` {k}" for g, v, k in unused] + [""]
    return "\n".join(out)


def summary(published, rejected, files, fallback, uses, findings, suppressed, coverage):
    lines = [
        "### API version drift",
        "",
        f"- Index: {sum(map(len, published.values()))} apiVersion/kind entries"
        f" ({rejected} rejected)",
        f"- Manifests: {files} files, {len(uses)} distinct apiVersion/kind uses",
        f"- Index coverage of repo CRD kinds: {coverage:.0%}",
        f"- Findings: {len(findings['unpublished'])} unpublished,"
        f" {len(findings['unknown'])} unknown, {len(findings['stale'])} stale,"
        f" {len(suppressed)} allowlisted",
    ]
    if fallback:
        lines.append(f"- Parsed by regex fallback (top-level only): {', '.join(fallback)}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default=INDEX_URL, help="all.json path or https URL")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--allow", default=str(HERE / "api-version-drift-allow.yaml"))
    ap.add_argument("--out", default="-", help="report file, or - for stdout")
    args = ap.parse_args(argv)
    if yaml is None:
        print("error: PyYAML is required", file=sys.stderr)
        return 2
    try:
        published, rejected = load_index(args.index)
        missing = [f"{g} {k}" for g, k in SENTINELS if (g, k) not in published]
        if missing:
            raise Problem(f"index is missing sentinel kinds: {', '.join(missing)}")
        allow = load_allow(pathlib.Path(args.allow))
        uses, files, fallback = scan(pathlib.Path(args.root).resolve())
        findings, suppressed, unused, considered = classify(uses, published, allow)
        coverage = (sum(1 for k in considered if k in published) / len(considered)
                    if considered else 1.0)
        if coverage < MIN_COVERAGE:
            raise Problem(f"index covers only {coverage:.0%} of the repo's CRD kinds")
    except Problem as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    text = summary(published, rejected, files, fallback, uses, findings, suppressed, coverage)
    sys.stderr.write(text)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(text)

    report = render(findings, unused, uses)
    if args.out == "-":
        sys.stdout.write(report)
    else:
        pathlib.Path(args.out).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
