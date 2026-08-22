# Talos

Declarative [Talos Linux](https://www.talos.dev) machine configuration for the cluster, built from
composable patches. Nothing in this directory is applied automatically; configs are rendered on
demand and pushed to nodes with `talosctl`.

## Layout

| Path                                    | Purpose                                                                   |
| --------------------------------------- | ------------------------------------------------------------------------- |
| `cluster.yaml.j2`                       | Documents applied to every node                                           |
| `controlplane.yaml.j2`                  | Control-plane-only documents, including `machine.type`                    |
| `workers.yaml.j2`                       | Worker-only documents (does not exist yet; created with the first worker) |
| `nodes/<role>/<node>.yaml.j2`           | Per-node documents (hostname, install disk, links/bonds)                  |
| `nodes/<role>/<node>.schematic.yaml.j2` | Optional per-node schematic override (complete file, not a delta)         |
| `schematic.yaml.j2`                     | Shared [Image Factory](https://factory.talos.dev) schematic (baremetal)   |
| `mod.just`                              | Recipes (`just talos ...`)                                                |

## Rendering

`just talos render-config <node>` builds the final machine config in three layers:

```
talosctl machineconfig patch <(cluster.yaml.j2) \
    -p @<(controlplane.yaml.j2 | workers.yaml.j2) \
    -p @<(nodes/<role>/<node>.yaml.j2)
```

Each layer passes through `minijinja-cli` (strict templating; the schematic ID arrives as a `-D`
define) and `vals` (1Password `ref+op://` resolution) before `talosctl` merges them. Later patches
strategically merge into earlier ones: maps deep-merge, documents with the same kind/name
deep-merge, new documents are appended.

Two conventions keep the layers honest:

- **Directory placement is the single source of truth for a node's role.** The role patch is chosen
  by which `nodes/<role>/` directory contains the node file, and `machine.type` is set by the role
  patch, not the node file.
- **Secrets never live in this repo.** All sensitive values are `ref+op://kubernetes/talos/...`
  references resolved at render time.

The cluster runs Talos 1.13, so the content is still the legacy `v1alpha1` `machine:`/`cluster:`
document plus the multi-document kinds 1.13 supports. Migrating the legacy fields to the 1.14
document kinds (`KubeletConfig`, `KubeAPIServerConfig`, ...) is part of the 1.14 upgrade, not this
layout.

## Schematics

The schematic defines the Image Factory build (system extensions, kernel args). `just talos
schematic-id <node>` POSTs it to the factory and gets back a content-addressed ID, which is
templated into `machine.install.image` and used by `download-image` and `upgrade-node`.

Resolution is per node: `nodes/<role>/<node>.schematic.yaml.j2` wins when present, otherwise the
shared `schematic.yaml.j2` applies. `matalos-c1` is a VM and carries an override (guest agent, no
iGPU); it also overrides `machine.install.image` in its node file to the generic `installer`
path, where the baremetal nodes use `metal-installer` from `cluster.yaml.j2`.

`just talos download-image <node> <version> iso=true` bakes the static bond + `ip=` kernel args
(from the node file's `# talos:node-ip=` marker) into a baremetal install ISO.

## Gotchas

- `machine.ca` and `cluster.ca` merge as a cert+key **unit**: a patch supplying only `key` blanks
  `crt`. This is why `controlplane.yaml.j2` repeats the `crt` references alongside the keys.
- Rendering a worker before `workers.yaml.j2` and `nodes/workers/` exist fails loudly. Adding the
  first worker means creating `workers.yaml.j2` (with `machine: { type: worker }` and a `ca` block
  carrying `crt` only) plus `nodes/workers/<node>.yaml.j2`.
- Talos dry-run diffs print secret material (tokens, CA keys, the secretbox key). Redact before
  sharing a diff anywhere.

## Common tasks

```sh
just talos render-config <node>          # render a node's full machine config to stdout
just talos apply-node <node>             # render and apply (talosctl apply-config)
just talos apply-node <node> --dry-run   # show what would change, apply nothing
just talos upgrade-node <node>           # upgrade Talos using the node's schematic image
just talos upgrade-k8s <version>         # upgrade Kubernetes across the cluster
just talos download-image <node> <version>   # fetch a metal ISO from the Image Factory
```

Verify a refactor of these templates by diffing rendered output before and after, then confirming
`just talos apply-node <node> --dry-run` reports no changes on every node.
