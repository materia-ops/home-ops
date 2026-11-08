import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ansible_last_applied as la  # noqa: E402


class WorkflowFileTest(unittest.TestCase):
    def test_strips_repo_path_and_ref(self):
        ref = "materia-ops/home-ops/.github/workflows/ansible.yaml@refs/heads/main"
        self.assertEqual(la.workflow_file(ref), "ansible.yaml")

    def test_branch_ref_with_slashes(self):
        ref = "o/r/.github/workflows/ansible.yaml@refs/heads/ci/some-branch"
        self.assertEqual(la.workflow_file(ref), "ansible.yaml")


class LastAppliedTest(unittest.TestCase):
    def test_newest_run(self):
        runs = [{"id": 3, "head_sha": "c"}, {"id": 2, "head_sha": "b"}]
        self.assertEqual(la.last_applied(runs, "9"), "c")

    def test_skips_current_run_on_rerun(self):
        # A rerun keeps its run id and its earlier attempt may be listed as
        # success; it must diff from the run before it, not from itself.
        runs = [{"id": 3, "head_sha": "c"}, {"id": 2, "head_sha": "b"}]
        self.assertEqual(la.last_applied(runs, "3"), "b")

    def test_no_successful_run(self):
        self.assertEqual(la.last_applied([], "1"), "")
        self.assertEqual(la.last_applied([{"id": 1, "head_sha": "a"}], 1), "")


if __name__ == "__main__":
    unittest.main()
