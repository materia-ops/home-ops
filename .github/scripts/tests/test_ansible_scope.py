import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ansible_scope as sc  # noqa: E402

INVENTORY = """\
all:
  vars:
    ansible_user: ansible
  children:
    proxmox:
      vars: &remote_vars # comment
        ansible_python_interpreter: /usr/bin/python3
      hosts:
        pve-0:
          ansible_host: pve-0.internal
    raspberry_pis:
      vars: *remote_vars
      # Order matters for serial rollouts
      hosts:
        pi-1:
          ansible_host: pi-1.internal
        pi-0:
          ansible_host: pi-0.internal
"""
HOSTS = sc.inventory_hosts(INVENTORY)
HV = "infrastructure/inventory/host_vars/"


def scope(*paths):
    return sc.scope(list(paths), HOSTS)


class InventoryHostsTest(unittest.TestCase):
    def test_hosts_only_not_groups_or_vars(self):
        self.assertEqual(HOSTS, {"pve-0", "pi-0", "pi-1"})

    def test_real_inventory(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "infrastructure", "inventory", "hosts.yaml"
        )
        with open(path, encoding="utf-8") as fh:
            hosts = sc.inventory_hosts(fh.read())
        # Hosts get added; groups and keywords must never parse as hosts.
        self.assertTrue({"pve-0", "pi-0", "pi-1"} <= hosts)
        self.assertFalse(hosts & {"all", "vars", "children", "hosts", "proxmox", "raspberry_pis"})


class ScopeTest(unittest.TestCase):
    def test_host_vars_limit_to_that_host_with_every_tag(self):
        # #2551: a pi-0 domain entry must not run against pve-0.
        self.assertEqual(scope(HV + "pi-0.yaml"), ("", "pi-0"))

    def test_two_host_vars(self):
        self.assertEqual(scope(HV + "pi-1.yaml", HV + "pi-0.yaml"), ("", "pi-0,pi-1"))

    def test_host_vars_for_host_not_in_inventory_runs_everywhere(self):
        self.assertEqual(scope(HV + "pikvm.yaml"), ("", ""))

    def test_role_is_its_tag_on_every_host(self):
        self.assertEqual(scope("infrastructure/roles/pihole/tasks/lists.yaml"), ("pihole", ""))

    def test_roles_union(self):
        self.assertEqual(
            scope(
                "infrastructure/roles/pihole/tasks/main.yaml",
                "infrastructure/roles/network/defaults/main.yaml",
            ),
            ("network,pihole", ""),
        )

    def test_talos_nodes_feed_pihole(self):
        self.assertEqual(scope("talos/nodes/matalos-c1.yaml.j2"), ("pihole", ""))

    def test_group_vars_is_observability(self):
        self.assertEqual(scope("infrastructure/inventory/group_vars/all.yaml"), ("observability", ""))

    def test_structural_runs_everything(self):
        for path in (
            "infrastructure/playbook.yaml",
            "infrastructure/inventory/hosts.yaml",
            "infrastructure/requirements.txt",
            "infrastructure/ansible.cfg",
            "infrastructure/Dockerfile",
            "infrastructure/known_hosts",
        ):
            with self.subTest(path=path):
                self.assertEqual(scope(path, HV + "pi-0.yaml"), ("", ""))

    def test_unknown_role_widens_instead_of_being_skipped(self):
        # The old inline mapping kept only the recognised tag and dropped this.
        self.assertEqual(
            scope(
                "infrastructure/roles/pihole/tasks/main.yaml",
                "infrastructure/roles/pikvm/tasks/main.yaml",
            ),
            ("", ""),
        )

    def test_host_vars_beside_a_role_keeps_every_tag(self):
        # The old mapping ran only --tags pihole, skipping pi-0's other plays.
        self.assertEqual(
            scope("infrastructure/roles/pihole/tasks/main.yaml", HV + "pi-0.yaml"), ("", "")
        )

    def test_paths_that_cannot_change_a_host_are_ignored(self):
        self.assertEqual(
            scope(
                "kubernetes/apps/network/pihole-nebula-sync/app/helmrelease.yaml",
                "docs/cicd.md",
                ".github/workflows/ansible.yaml",
                "infrastructure/roles/pihole/README.md",
                HV + "pi-0.yaml",
            ),
            ("", "pi-0"),
        )

    def test_nothing_counted_runs_everything(self):
        self.assertEqual(scope(), ("", ""))
        self.assertEqual(scope("kubernetes/apps/x.yaml"), ("", ""))


if __name__ == "__main__":
    unittest.main()
