"""Tests for upgrade_evidence.py.

Offline by default: each fixtures/prN directory holds a real PR's diff, body
and title plus a recorded network cache, and expected.txt is the golden output.
Run from the repo root:

  python3 -m unittest discover -s .github/scripts/tests -v

Re-record a fixture after a deliberate behaviour change (needs gh + helm):

  python3 .github/scripts/upgrade_evidence.py --diff-file F/diff.patch \
    --body-file F/body.txt --title "$(cat F/title.txt)" --root F \
    --cache F/cache --record --out F/expected.txt

UPGRADE_EVIDENCE_LIVE=1 additionally runs the script against the live APIs.
"""
import importlib.util
import os
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
spec = importlib.util.spec_from_file_location("upgrade_evidence",
                                              HERE.parent / "upgrade_evidence.py")
ue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ue)


def run_fixture(name, mode="replay"):
    d = FIXTURES / name
    net = ue.Net(str(d / "cache"), mode)
    return ue.build(net, (d / "diff.patch").read_text(encoding="utf-8"),
                    (d / "body.txt").read_text(encoding="utf-8"),
                    (d / "title.txt").read_text(encoding="utf-8").strip(),
                    ue.local_reader(str(d)))


class Golden(unittest.TestCase):
    def test_fixtures_match_golden_output(self):
        names = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())
        self.assertGreaterEqual(len(names), 6)
        for name in names:
            with self.subTest(name):
                expected = (FIXTURES / name / "expected.txt").read_text(encoding="utf-8")
                self.assertEqual(run_fixture(name), expected)


class RealPRs(unittest.TestCase):
    def test_1728_surfaces_inner_external_dns_annotation_prefix(self):
        out = run_fixture("pr1728")
        self.assertIn("| external-dns (appVersion) | `0.21.0` → `0.22.0` | inner-app |"
                      " github.com/kubernetes-sigs/external-dns |", out)
        self.assertIn("releases/tag/v0.22.0", out)
        self.assertIn("default annotation prefix is now `external-dns.kubernetes.io/`", out)
        self.assertIn("external-dns-helm-chart-1.22.0", out)

    def test_1734_is_labelled_rollback(self):
        out = run_fixture("pr1734")
        self.assertIn("`1.22.0` → `1.21.1` | **ROLLBACK**", out)
        self.assertIn("`0.22.0` → `0.21.0` | **ROLLBACK**", out)
        self.assertIn("ones being UNDONE", out)

    def test_1924_rook_group_normalises_v_prefix(self):
        out = run_fixture("pr1924")
        self.assertIn("ghcr.io/rook/rook-ceph, ghcr.io/rook/rook-ceph-cluster", out)
        self.assertIn("`v1.20.8` → `1.21.0`", out)
        self.assertIn("releases/tag/v1.21.0", out)
        self.assertIn("Helm OCI chart tags no longer include the `v` prefix", out)

    def test_1761_talos_group_collapses_to_one_row(self):
        out = run_fixture("pr1761")
        rows = [ln for ln in out.splitlines() if ln.startswith("| ") and "talos" in ln]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("factory.talos.dev/metal-installer", rows[0])
        self.assertIn("github.com/siderolabs/talos", rows[0])

    def test_1955_action_bump(self):
        out = run_fixture("pr1955")
        self.assertIn("`v1.0.242@6c69018` → `v1.0.243@86d88e6` | action", out)
        self.assertIn("releases/tag/v1.0.243", out)

    def test_1917_charts_mirror_chart_and_app_rows(self):
        out = run_fixture("pr1917")
        self.assertIn("releases/tag/descheduler-helm-chart-0.37.0", out)
        self.assertIn("releases/tag/v0.37.0", out)

    def test_1953_digest_only_is_rebuild(self):
        out = run_fixture("pr1953")
        self.assertIn("rebuild (digest only)", out)
        self.assertNotIn("UNRESOLVED", out)


def rel(tag, body="notes", pre=False):
    return (tag, "", body, f"https://example.invalid/{tag}", pre)


class Units(unittest.TestCase):
    def test_parse_diff_kinds(self):
        diff = """\
diff --git a/.mise/config.toml b/.mise/config.toml
--- a/.mise/config.toml
+++ b/.mise/config.toml
@@ -1,3 +1,3 @@
-"aqua:siderolabs/talos" = "1.14.0"
+"aqua:siderolabs/talos" = "1.14.1"
diff --git a/x/helmrelease.yaml b/x/helmrelease.yaml
--- a/x/helmrelease.yaml
+++ b/x/helmrelease.yaml
@@ -5,4 +5,4 @@
             image:
               repository: ghcr.io/autobrr/qui
-              tag: v1.31.0@sha256:aaaaaaa
+              tag: v1.31.1@sha256:bbbbbbb
diff --git a/x/upgrade.yaml b/x/upgrade.yaml
--- a/x/upgrade.yaml
+++ b/x/upgrade.yaml
@@ -1,3 +1,3 @@
     # renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
-    version: v1.36.0
+    version: v1.37.1
"""
        bumps = ue.parse_diff(diff, ue.local_reader("/nonexistent"))
        got = {(b["kind"], b["name"], b["old"], b["new"]) for b in bumps}
        self.assertEqual(got, {
            ("mise", "siderolabs/talos", "1.14.0", "1.14.1"),
            ("image", "ghcr.io/autobrr/qui", "v1.31.0@sha256:aaaaaaa", "v1.31.1@sha256:bbbbbbb"),
            ("docker", "ghcr.io/siderolabs/kubelet", "v1.36.0", "v1.37.1"),
        })

    def test_renovate_annotation_covers_only_the_next_line(self):
        diff = """\
diff --git a/vars.yaml b/vars.yaml
--- a/vars.yaml
+++ b/vars.yaml
@@ -1,4 +1,4 @@
 # renovate: datasource=github-releases depName=prometheus/node_exporter
 node_exporter_version: "1.12.1"
-other_version: 1.0
+other_version: 1.1
"""
        self.assertEqual(ue.parse_diff(diff, ue.local_reader("/nonexistent")), [])

    def test_body_parses_only_the_update_table(self):
        body = ("| Package | Change |\n|---|---|\n| [o/r](https://github.com/o/r) | `1` → `2` |\n"
                "\n<details>\n\n| Flag | Rename |\n|---|---|\n| x | `--a` → `--b` |\n")
        self.assertEqual([r["name"] for r in ue.parse_body(body)], ["o/r"])

    def test_prerelease_ordering(self):
        self.assertGreater(ue.vkey("v2.0.0-rc.10"), ue.vkey("v2.0.0-rc.9"))
        self.assertGreater(ue.vkey("v2.0.0"), ue.vkey("v2.0.0-rc.10"))
        self.assertFalse(ue.is_prerelease("dind"))

    def test_direction(self):
        self.assertEqual(ue.direction("1.22.0", "1.21.1"), "rollback")
        self.assertEqual(ue.direction("v1.2@sha256:a", "v1.2@sha256:b"), "rebuild")
        self.assertEqual(ue.direction("v1.20.8", "1.21.0"), "upgrade")
        self.assertEqual(ue.direction("20260101", "20260201"), "upgrade")

    def test_select_prefers_chart_tags_for_charts_and_app_tags_otherwise(self):
        rels = [rel("descheduler-helm-chart-0.37.0"), rel("v0.37.0"),
                rel("descheduler-helm-chart-0.36.0"), rel("v0.36.0")]
        picked, found, prefix, boundary = ue.select_releases(
            rels, "ghcr.io/x/descheduler", "0.36.0", "0.37.0", chart=True)
        self.assertEqual([r[0] for _, r in picked], ["descheduler-helm-chart-0.37.0"])
        self.assertTrue(found)
        self.assertEqual(boundary[0], "descheduler-helm-chart-0.36.0")
        picked, *_ = ue.select_releases(rels, "descheduler (appVersion)", "0.36.0", "0.37.0")
        self.assertEqual([r[0] for _, r in picked], ["v0.37.0"])

    def test_select_covers_whole_range_and_skips_prereleases(self):
        rels = [rel(f"v1.{m}.{p}") for m in range(3, 0, -1) for p in range(5, -1, -1)]
        rels.insert(0, rel("v1.3.0-rc.1", pre=True))
        picked, *_ = ue.select_releases(rels, "o/r", "v1.1.2", "v1.3.0")
        tags = [r[0] for _, r in picked]
        self.assertEqual(len(tags), 3 + 6 + 1)
        self.assertNotIn("v1.3.0-rc.1", tags)

    def test_untrusted_body_cannot_break_out_of_fence(self):
        text, _ = ue.render_release("1.0.0", rel("v1.0.0", "<!-- hidden -->\n```\nescape\n````"))
        self.assertNotIn("hidden", text)
        self.assertEqual(text.count("````"), 2)

    def test_dependency_cap_omits_releases_explicitly(self):
        big = "breaking change\n\n" + "x" * 6000
        rels = [(f"1.{i}.0", rel(f"v1.{i}.0", big)) for i in range(10, 0, -1)]
        bump = {"names": ["o/r"], "paths": [], "kind": "image", "old": "1.0.0",
                "new": "1.10.0", "direction": "upgrade", "range": ("1.0.0", "1.10.0"),
                "resolved": {"host": "github.com", "slug": "o/r", "via": "test",
                             "releases": rels, "found_new": True, "capped": False}}
        out = ue.render([bump])
        self.assertIn("OMITTED for size", out)
        self.assertLessEqual(len(out.encode()), ue.MAX_DEP_BYTES + 2048)
        self.assertIn("| truncated |", out)

    def test_total_cap_drops_whole_sections(self):
        big = "breaking change\n\n" + "x" * 6000
        bumps = []
        for n in range(8):
            rels = [(f"1.{i}.0", rel(f"v1.{i}.0", big)) for i in range(4, 0, -1)]
            bumps.append({"names": [f"o/r{n}"], "paths": [], "kind": "image",
                          "old": "1.0.0", "new": "1.4.0", "direction": "upgrade",
                          "range": ("1.0.0", "1.4.0"),
                          "resolved": {"host": "github.com", "slug": f"o/r{n}",
                                       "via": "test", "releases": rels,
                                       "found_new": True, "capped": False}})
        out = ue.render(bumps)
        self.assertLessEqual(len(out.encode()), ue.MAX_TOTAL_BYTES + 4096)
        self.assertIn("truncated (total cap)", out)
        self.assertEqual(out.count("````") % 2, 0)

    def test_unresolved_is_explicit(self):
        bump = {"names": ["thing"], "paths": [], "kind": "image", "old": "1", "new": "2",
                "direction": "upgrade", "range": ("1", "2"), "resolved": None,
                "cands": [("github.com", "a/b", "name pattern")]}
        self.assertIn("UNRESOLVED", ue.render([bump]))

    def test_body_table_cross_check(self):
        body = ("| Package | Update | Change |\n|---|---|---|\n"
                "| [ghcr.io/x/flux-instance](https://fluxoperator.dev) "
                "([source](https://redirect.github.com/controlplaneio-fluxcd/flux-operator))"
                " | minor | `0.59.0` → `0.60.0` |\n")
        rows = ue.parse_body(body)
        self.assertEqual(rows[0]["source"], ("github.com", "controlplaneio-fluxcd/flux-operator"))
        merged = ue.merge_body([], rows)
        self.assertEqual(merged[0]["kind"], "pr-body")

    def test_overrides_longest_prefix(self):
        ov = {"ghcr.io/rook": "rook/rook", "ghcr.io/rook/ceph": "ceph/ceph",
              "x": "codeberg.org/o/r"}
        self.assertEqual(ue.override_for("ghcr.io/rook/rook-ceph", ov), ("github.com", "rook/rook"))
        self.assertEqual(ue.override_for("ghcr.io/rook/ceph", ov), ("github.com", "ceph/ceph"))
        self.assertEqual(ue.override_for("x/y", ov), ("codeberg.org", "o/r"))
        parsed = ue.load_overrides()
        self.assertIn("ghcr.io/victoriametrics/helm-charts/victoria-metrics-k8s-stack#app",
                      parsed)
        saved, ue.yaml = ue.yaml, None
        try:
            self.assertEqual(ue.load_overrides(), parsed)  # PyYAML-less fallback
        finally:
            ue.yaml = saved


@unittest.skipUnless(os.environ.get("UPGRADE_EVIDENCE_LIVE"), "network test")
class Live(unittest.TestCase):
    def test_1728_live(self):
        out = run_fixture("pr1728", mode=None)
        self.assertIn("annotation prefix", out)


if __name__ == "__main__":
    unittest.main()
