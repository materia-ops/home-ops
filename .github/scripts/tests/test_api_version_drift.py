"""Tests for api_version_drift.py.

Offline: each test writes a small all.json index and kubernetes/ tree into a
temp directory. Run from the repo root:

  python3 -m unittest discover -s .github/scripts/tests -v
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import textwrap
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("api_version_drift",
                                              HERE.parent / "api_version_drift.py")
avd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(avd)

BASE_INDEX = [
    ("external-secrets.io/v1", "ExternalSecret"),
    ("external-secrets.io/v1beta1", "ExternalSecret"),
    ("gateway.networking.k8s.io/v1", "ReferenceGrant"),
    ("gateway.networking.k8s.io/v1beta1", "ReferenceGrant"),
    ("helm.toolkit.fluxcd.io/v2", "HelmRelease"),
    ("kustomize.toolkit.fluxcd.io/v1", "Kustomization"),
]


def index(entries):
    return {"oneOf": [{"allOf": [{"properties": {"apiVersion": {"enum": [av]},
                                                 "kind": {"enum": [kind]}}},
                                 {"$ref": "x.json"}]} for av, kind in entries]}


class UnitTest(unittest.TestCase):
    def test_rank_follows_kubernetes_priority(self):
        order = ["v1alpha1", "v2alpha1", "v1beta1", "v1beta2", "v2beta1", "v1", "v2"]
        self.assertEqual(sorted(reversed(order), key=avd.rank), order)
        self.assertIsNone(avd.rank("v1beta"))
        self.assertIsNone(avd.rank("v0"))

    def test_index_entries_with_unsafe_names_rejected(self):
        published, rejected = avd.parse_index(index(BASE_INDEX + [
            ("evil.io/v1", "Kind|@user"),
            ("Evil.io/v1", "Kind"),
            ("evil.io/v1](x)", "Kind"),
        ]))
        self.assertEqual(rejected, 3)
        self.assertNotIn(("evil.io", "Kind|@user"), published)

    def test_index_with_wrong_shape_is_a_problem(self):
        for data in ({"oneOf": [{"allOf": 5}]},
                     {"oneOf": [{"allOf": [{"properties": {"apiVersion": "x"}}]}]},
                     {"oneOf": [{"allOf": [{"properties": {"apiVersion": {"enum": 5},
                                                           "kind": {"enum": ["K"]}}}]}]}):
            with self.assertRaises(avd.Problem, msg=data):
                avd.parse_index(data)

    def test_parse_pair_skips_core_and_substitutions_only(self):
        self.assertEqual(avd.parse_pair("example.io/v1", "Widget"),
                         ("example.io", "v1", "Widget"))
        for pair in (("v1", "ConfigMap"), ("${GROUP}/v1", "Thing"), ("apps/v1", "${KIND}")):
            self.assertEqual(avd.parse_pair(*pair), "skip", pair)
        for pair in (("example.io/v1beta", "Widget"), (None, "Widget"),
                     ("example.io/v1", "widget"), ("v1", "lowercase"), ("vX", "ConfigMap")):
            self.assertEqual(avd.parse_pair(*pair), "bad", pair)

    def test_shown_neutralises_markdown(self):
        out = avd.shown("Foo|@user](x)`<b>\n")
        self.assertTrue(out.startswith("`Foo") and out.endswith("`"), out)
        self.assertFalse(set(out[1:-1]) & set("|@[]()`<>\n"), out)
        self.assertTrue(avd.shown("a" * 100).endswith("...`"))
        self.assertEqual(avd.shown(""), "(empty)")

    def test_shown_keeps_urls_inside_a_code_span(self):
        for value in ("https://evil.example/pwn", "www.evil.example"):
            self.assertEqual(avd.shown(value), f"`{value}`")


@unittest.skipIf(avd.yaml is None, "PyYAML not installed")
class DriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.allow = self.root / "allow.yaml"
        self.write_index(BASE_INDEX)
        self.write("kubernetes/apps/base.yaml", """\
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            ---
            apiVersion: kustomize.toolkit.fluxcd.io/v1
            kind: Kustomization
            ---
            apiVersion: external-secrets.io/v1
            kind: ExternalSecret
            """)

    def tearDown(self):
        self.tmp.cleanup()

    def write_index(self, entries):
        (self.root / "all.json").write_text(json.dumps(index(entries)), encoding="utf-8")

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = avd.main(["--index", str(self.root / "all.json"), "--root", str(self.root),
                             "--allow", str(self.allow)])
        return code, out.getvalue(), err.getvalue()

    def test_clean_repo_gives_empty_report(self):
        code, out, err = self.run_main()
        self.assertEqual((code, out), (0, ""))
        self.assertIn("0 stale", err)

    def test_stale_version_reported_with_newest(self):
        self.write("kubernetes/apps/rg.yaml", """\
            apiVersion: gateway.networking.k8s.io/v1beta1
            kind: ReferenceGrant
            """)
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(avd.MARKER))
        self.assertIn("### Newer version available", out)
        self.assertIn("| `gateway.networking.k8s.io/v1beta1` | `ReferenceGrant` | `v1` |", out)
        self.assertIn("`kubernetes/apps/rg.yaml`", out)

    def test_ga_beats_newer_major_alpha(self):
        self.write_index(BASE_INDEX + [("example.io/v1", "Widget"),
                                       ("example.io/v2alpha1", "Widget")])
        self.write("kubernetes/w.yaml", "apiVersion: example.io/v1\nkind: Widget\n")
        self.assertEqual(self.run_main()[1], "")

    def test_unpublished_and_unknown_kinds(self):
        # Enough covered kinds that one unknown kind stays above MIN_COVERAGE.
        extra = [("example.io/v1", f"K{i}") for i in range(10)]
        self.write_index(BASE_INDEX + extra)
        self.write("kubernetes/extra.yaml",
                   "\n---\n".join(f"apiVersion: {av}\nkind: {k}" for av, k in extra) + "\n")
        self.write("kubernetes/x.yaml", """\
            apiVersion: external-secrets.io/v1alpha1
            kind: ExternalSecret
            ---
            apiVersion: gone.example.io/v1
            kind: Removed
            """)
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("### Version not published by the cluster", out)
        self.assertIn("| `external-secrets.io/v1alpha1` | `ExternalSecret` | `v1, v1beta1` |", out)
        self.assertIn("### Kind not on the cluster", out)
        self.assertIn("`gone.example.io/v1` | `Removed`", out)

    def test_builtin_and_core_groups_skipped(self):
        self.write("kubernetes/k.yaml", """\
            apiVersion: kustomize.config.k8s.io/v1beta1
            kind: Kustomization
            ---
            apiVersion: apps/v1
            kind: Deployment
            ---
            apiVersion: v1
            kind: ConfigMap
            """)
        self.assertEqual(self.run_main()[1], "")

    def test_nested_refs_and_embedded_patches(self):
        self.write("kubernetes/ks.yaml", """\
            apiVersion: kustomize.toolkit.fluxcd.io/v1
            kind: Kustomization
            spec:
              healthChecks:
                - apiVersion: external-secrets.io/v1beta1
                  kind: ExternalSecret
                  name: a
              patches:
                - patch: |
                    apiVersion: gateway.networking.k8s.io/v1beta1
                    kind: ReferenceGrant
                    metadata:
                      name: b
            """)
        _, out, _ = self.run_main()
        self.assertIn("`external-secrets.io/v1beta1` | `ExternalSecret` | `v1` |", out)
        self.assertIn("`gateway.networking.k8s.io/v1beta1` | `ReferenceGrant` | `v1` |", out)

    def test_custom_tags_and_redefined_anchors_parse(self):
        self.write("kubernetes/blueprint.yaml", """\
            apiVersion: gateway.networking.k8s.io/v1beta1
            kind: ReferenceGrant
            metadata:
              name: !Find [authentik_flows.flow, [slug, x]]
              a: &key one
              b: &key two
              c: *key
            """)
        code, out, err = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("`ReferenceGrant` | `v1` |", out)
        self.assertNotIn("regex fallback", err)

    def test_unparseable_file_falls_back_to_regex(self):
        self.write("kubernetes/broken.yaml", """\
            apiVersion: gateway.networking.k8s.io/v1beta1
            kind: ReferenceGrant
            spec: [unclosed
            """)
        _, out, err = self.run_main()
        self.assertIn("`ReferenceGrant` | `v1` |", out)
        self.assertIn("regex fallback (top-level only): `kubernetes/broken.yaml`", err)

    def test_substituted_api_version_ignored(self):
        self.write("kubernetes/s.yaml", "apiVersion: ${GROUP}/v1\nkind: Thing\n")
        self.assertEqual(self.run_main()[1], "")

    def test_allowlist_suppresses_and_reports_unused_entries(self):
        self.write("kubernetes/rg.yaml", """\
            apiVersion: gateway.networking.k8s.io/v1beta1
            kind: ReferenceGrant
            """)
        self.allow.write_text(textwrap.dedent("""\
            allow:
              - apiVersion: gateway.networking.k8s.io/v1beta1
                kind: ReferenceGrant
                reason: test
              - apiVersion: example.io/v1beta1
                kind: Widget
                reason: no longer used
            """), encoding="utf-8")
        _, out, err = self.run_main()
        self.assertNotIn("ReferenceGrant", out)
        self.assertIn("### Allowlist entries that no longer match", out)
        self.assertIn("- `example.io/v1beta1` `Widget`", out)
        self.assertIn("1 allowlisted", err)

    def test_allowlist_entry_without_reason_fails(self):
        self.allow.write_text("allow:\n  - apiVersion: example.io/v1\n    kind: Widget\n",
                              encoding="utf-8")
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("needs apiVersion, kind and reason", err)

    def test_html_index_fails_loudly(self):
        (self.root / "all.json").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
        code, out, err = self.run_main()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("is not JSON", err)

    def test_missing_sentinel_fails(self):
        self.write_index([e for e in BASE_INDEX if e[1] != "HelmRelease"])
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("helm.toolkit.fluxcd.io HelmRelease", err)

    def test_low_coverage_fails(self):
        for i in range(5):
            self.write(f"kubernetes/u{i}.yaml", f"apiVersion: g{i}.example.io/v1\nkind: K{i}\n")
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("index covers only", err)

    def test_malformed_allowlist_fails(self):
        for text in ("allow: [unclosed\n", "- just a list\n", "allow: {a: 1}\n", "allow: {}\n",
                     "allow: " + "[" * 5000 + "]" * 5000 + "\n"):
            self.allow.write_text(text, encoding="utf-8")
            code, _, err = self.run_main()
            self.assertEqual(code, 2, text[:30])
            self.assertIn("error: allow.yaml", err)
            self.assertNotIn("Traceback", err)

    def test_empty_allowlist_forms_are_accepted(self):
        for text in ("", "# only a comment\n", "allow:\n", "allow: []\n"):
            self.allow.write_text(text, encoding="utf-8")
            self.assertEqual(self.run_main()[0], 0, repr(text))

    def test_missing_local_index_fails(self):
        (self.root / "all.json").unlink()
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("reading", err)

    def test_undecodable_manifest_fails_naming_file(self):
        (self.root / "kubernetes/bad.yaml").write_bytes(b"kind: \xff\n")
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("kubernetes/bad.yaml", err)

    def test_recursive_alias_does_not_crash(self):
        self.write("kubernetes/loop.yaml", """\
            apiVersion: gateway.networking.k8s.io/v1beta1
            kind: ReferenceGrant
            spec: &loop
              self: *loop
            """)
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("`ReferenceGrant` | `v1` |", out)

    def test_nested_string_fallback_is_reported(self):
        self.write("kubernetes/ks.yaml", """\
            apiVersion: kustomize.toolkit.fluxcd.io/v1
            kind: Kustomization
            spec:
              patches:
                - patch: |
                    apiVersion: gateway.networking.k8s.io/v1beta1
                    kind: ReferenceGrant
                    spec: [unclosed
            """)
        _, out, err = self.run_main()
        self.assertIn("`ReferenceGrant` | `v1` |", out)
        self.assertIn("regex fallback (top-level only): `kubernetes/ks.yaml`", err)

    def test_unparseable_pairs_are_reported_not_dropped(self):
        self.write("kubernetes/odd.yaml", """\
            apiVersion: example.io/v1beta
            kind: Widget
            ---
            apiVersion: !Sub "${Group}/v1"
            kind: Widget
            ---
            apiVersion: [example.io/v1]
            kind: Widget
            ---
            apiVersion: example.io/v1
            kind: {}
            ---
            apiVersion: https://evil.example/pwn
            kind: www.evil.example
            ---
            apiVersion: v1
            kind: ConfigMap
            ---
            apiVersion: apiextensions.k8s.io/v1
            kind: CustomResourceDefinition
            spec:
              versions:
                - schema:
                    openAPIV3Schema:
                      properties:
                        apiVersion: {type: string}
                        kind: {type: string}
            """)
        code, out, err = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("### apiVersion/kind the check could not parse", out)
        row = next(line for line in out.splitlines() if line.startswith("| `kubernetes/odd.yaml`"))
        for cell in ("`example.io/v1beta` `Widget`", "`None` `Widget`", "`example.io/v1` `{}`",
                     "`https://evil.example/pwn` `www.evil.example`"):
            self.assertIn(cell, row)
        self.assertNotIn("](", row)
        self.assertIn("5 unparseable", err)

    def test_deeply_nested_index_fails_cleanly(self):
        (self.root / "all.json").write_text("[" * 200000, encoding="utf-8")
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("is not JSON", err)

    def test_uppercase_yaml_extension_is_scanned(self):
        self.write("kubernetes/RG.YAML", """\
            apiVersion: gateway.networking.k8s.io/v1beta1
            kind: ReferenceGrant
            """)
        self.assertIn("`kubernetes/RG.YAML`", self.run_main()[1])

    def test_hostile_file_names_stay_inside_one_code_span(self):
        rg = "apiVersion: gateway.networking.k8s.io/v1beta1\nkind: ReferenceGrant\n"
        self.write("kubernetes/a` www.evil.example `.yaml", rg)
        self.write("kubernetes/b` @octocat `.yaml", rg)
        out = self.run_main()[1]
        self.assertIn("`kubernetes/a? www.evil.example ?.yaml`", out)
        self.assertIn("`kubernetes/b? ?octocat ?.yaml`", out)
        self.assertNotIn("@", out)

    def test_deeply_nested_manifest_falls_back_instead_of_crashing(self):
        self.write("kubernetes/deep.yaml",
                   "apiVersion: gateway.networking.k8s.io/v1beta1\nkind: ReferenceGrant\n"
                   "spec: " + "[" * 5000 + "]" * 5000 + "\n")
        code, out, err = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("`ReferenceGrant` | `v1` |", out)
        self.assertIn("regex fallback (top-level only): `kubernetes/deep.yaml`", err)


if __name__ == "__main__":
    unittest.main()
