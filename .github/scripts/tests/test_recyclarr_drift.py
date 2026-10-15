"""Tests for recyclarr_drift.py.

Offline: each test builds a minimal TRaSH Guides tree and recyclarr config in a
temp directory. Run from the repo root:

  python3 -m unittest discover -s .github/scripts/tests -v
"""
import importlib.util
import json
import os
import pathlib
import shutil
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("recyclarr_drift",
                                              HERE.parent / "recyclarr_drift.py")
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)

PROFILE = "p" * 32
CONFIG = f"""\
sonarr:
  tv:
    base_url: http://sonarr
    api_key: !env_var SONARR_API_KEY
    quality_profiles:
      - trash_id: {PROFILE}
    custom_format_groups:
      add:
        - trash_id: g-unwanted
          select:
            - cf-scene
    custom_formats:
      - trash_ids:
          - cf-flux
        assign_scores_to:
          - name: WEB
            score: 51
"""


def group(gid, name, cfs, default=False, include=(PROFILE,)):
    return {"trash_id": gid, "name": name, "default": "true" if default else "false",
            "custom_formats": cfs,
            "quality_profiles": {"include": {f"profile-{i}": p for i, p in enumerate(include)}}}


def cf(cid, name, required=False, default=False):
    return {"trash_id": cid, "name": name, "required": required, "default": default}


class DriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.trash = self.root / "trash"
        self.config_dir = self.root / "config"
        self.baseline = self.root / "baseline.json"
        self.config_dir.mkdir()
        (self.config_dir / "sonarr.yaml").write_text(CONFIG, encoding="utf-8")
        self.groups = {
            "g-unwanted": group("g-unwanted", "[Unwanted] Unwanted Formats", [
                cf("cf-lq", "LQ", default=True),
                cf("cf-scene", "Scene"),
                cf("cf-retags", "Retags"),
            ], default=True),
            "g-hdr": group("g-hdr", "[HDR Formats] HDR", [cf("cf-hdr", "HDR", required=True)],
                           default=True),
            "g-uk": group("g-uk", "[Streaming Services] UK", [cf("cf-ip", "IP", required=True)]),
            "g-other": group("g-other", "Other profile only", [cf("cf-x", "X")],
                             include=("q" * 32,)),
        }
        self.cfs = {"cf-flux": "FLUX"}
        self.profiles = [PROFILE]

    def tearDown(self):
        self.tmp.cleanup()

    def write_trash(self):
        shutil.rmtree(self.trash, ignore_errors=True)
        base = self.trash / "docs" / "json" / "sonarr"
        for sub in ("cf-groups", "cf", "quality-profiles"):
            (base / sub).mkdir(parents=True, exist_ok=True)
            (self.trash / "docs" / "json" / "radarr" / sub).mkdir(parents=True, exist_ok=True)
        for g in self.groups.values():
            (base / "cf-groups" / f"{g['trash_id']}.json").write_text(json.dumps(g))
        for cid, name in self.cfs.items():
            (base / "cf" / f"{cid}.json").write_text(json.dumps({"trash_id": cid, "name": name}))
        for pid in self.profiles:
            (base / "quality-profiles" / f"{pid}.json").write_text(json.dumps({"trash_id": pid}))

    def report(self, update=False):
        self.write_trash()
        return rd.run(str(self.trash), str(self.config_dir), str(self.baseline), update, "test")

    def accept(self):
        self.assertEqual(self.report(update=True), "")

    def test_clean_after_baseline(self):
        self.accept()
        self.assertEqual(self.report(), "")

    def test_baseline_shape(self):
        self.accept()
        data = json.loads(self.baseline.read_text())
        inst = data["instances"]["sonarr/tv"]
        # every group offered to our profile, synced or not; never other profiles' groups
        self.assertEqual(set(inst["groups"]), {"g-unwanted", "g-hdr", "g-uk"})
        # CF choices only for synced groups, and never required CFs
        self.assertEqual(inst["cfs"], {"g-hdr": {},
                                       "g-unwanted": {"cf-lq": "LQ", "cf-retags": "Retags",
                                                      "cf-scene": "Scene"}})

    def test_new_optional_group_needs_decision(self):
        self.accept()
        self.groups["g-fr"] = group("g-fr", "[Streaming Services] French", [cf("cf-c", "C")])
        out = self.report()
        self.assertIn("New optional group **[Streaming Services] French** (`g-fr`): decide", out)
        self.assertIn(rd.MARKER, out)

    def test_new_default_group_is_informational(self):
        self.accept()
        self.groups["g-audio"] = group("g-audio", "[Audio] Audio Formats",
                                       [cf("cf-a", "A", default=True)], default=True)
        self.assertIn("New default group **[Audio] Audio Formats** (`g-audio`): already syncing",
                      self.report())

    def test_new_cfs_in_synced_group(self):
        self.accept()
        self.groups["g-unwanted"]["custom_formats"] += [cf("cf-obf", "Obfuscated"),
                                                        cf("cf-ext", "Extras", default=True)]
        out = self.report()
        self.assertIn("new optional CF **Obfuscated** (`cf-obf`): decide", out)
        self.assertIn("new default CF **Extras** (`cf-ext`): already syncing", out)

    def test_new_cf_in_unsynced_group_is_ignored(self):
        self.accept()
        self.groups["g-uk"]["custom_formats"].append(cf("cf-now", "NOW"))
        self.assertEqual(self.report(), "")

    def test_select_promoted_to_default_is_flagged(self):
        self.groups["g-unwanted"]["custom_formats"][1]["default"] = True
        self.accept()
        self.assertIn("selected CF Scene is now default", self.report())

    def test_stale_references_are_flagged(self):
        self.accept()
        del self.groups["g-unwanted"]
        self.cfs = {}
        self.profiles = []
        out = self.report()
        self.assertIn("references unknown group `g-unwanted`", out)
        self.assertIn("references unknown CF `cf-flux`", out)
        self.assertIn(f"quality profile `{PROFILE}` no longer exists upstream", out)


if __name__ == "__main__":
    unittest.main()
