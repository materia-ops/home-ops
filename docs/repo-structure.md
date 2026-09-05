# Repository Structure

How this repository is organised, the anatomy of an app, and the conventions that keep
it consistent. See [architecture.md](./architecture.md) for what the cluster looks like
at runtime and [repo-workflow.md](./repo-workflow.md) for how to make changes.

## Top level

| Path | Purpose |
| :--- | :--- |
| [`kubernetes/apps/`](../kubernetes/apps) | Everything Flux deploys, one directory per namespace |
| [`kubernetes/components/`](../kubernetes/components) | Reusable Kustomize components apps opt into |
| [`kubernetes/flux/cluster/`](../kubernetes/flux/cluster) | The single Flux entrypoint (`cluster-apps` Kustomization) |
| [`talos/`](../talos) | Talos machine configuration (minijinja templates + per-node overrides) |
| [`bootstrap/`](../bootstrap) | Day-0 bring-up: helmfile (CRDs, then core apps) and kustomize resources |
| [`infrastructure/`](../infrastructure) | Ansible for out-of-cluster hosts (the Pi-holes: dnscrypt, observability) |
| [`.github/workflows/`](../.github/workflows) | CI — see [cicd.md](./cicd.md) |
| [`.mise/`](../.mise/config.toml) | Toolchain versions (talosctl, flux, helmfile, kubectl, …) — `mise install` gets a working environment |
| [`.justfile`](../.justfile) | Task runner — `just` lists recipes, grouped into `bootstrap`, `kube`, and `talos` modules |
| `docs/` | This documentation (committed); work notes live in the private materia-vault |

## Anatomy of an app

Every app follows the same two-layer pattern:

```text
kubernetes/apps/<namespace>/<app>/
├── ks.yaml            # Flux Kustomization: wiring, dependencies, components, substitutions
└── app/
    ├── kustomization.yaml
    ├── helmrelease.yaml       # usually bjw-s app-template or an upstream chart
    ├── ocirepository.yaml     # chart source (OCI)
    ├── externalsecret.yaml    # 1Password → Secret via ESO (if needed)
    ├── httproute.yaml         # attachment to envoy-internal / envoy-external (if routed)
    └── pvc.yaml / *.yaml      # anything else the app needs
```

The `ks.yaml` is where the interesting wiring happens:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app qbittorrent
spec:
  components:                        # opt into shared behavior
    - ../../../../components/kopiur/backup
    - ../../../../components/zeroscaler
  dependsOn:                         # ordering across namespaces
    - name: rook-ceph-cluster
      namespace: rook-ceph
  path: ./kubernetes/apps/torrents/qbittorrent/app
  postBuild:
    substitute:                      # parameterise the components
      APP: *app
      KOPIUR_CAPACITY: 5Gi
  targetNamespace: torrents
```

Namespace directories carry a `namespace.yaml` and a `kustomization.yaml` listing their
apps' `ks.yaml` files.

## Components

Shared behavior lives in [`kubernetes/components/`](../kubernetes/components) and is
mixed into apps via `spec.components`:

| Component | What opting in gives you |
| :--- | :--- |
| `alerts` | Flux `Alert`/`Provider` routing reconciliation errors to Alertmanager (plus a GitHub commit-status variant) |
| `kopiur/backup` | The standard backup opt-in: everything in `kopiur/snapshot` **plus** the app PVC (`KOPIUR_CAPACITY`, `KOPIUR_STORAGECLASS`, owned here) and a bootstrap `Restore` that populates it from the latest snapshot. The component owns the PVC, so capacity changes happen here; a bound PVC cannot be re-pointed at the `Restore` afterwards (`dataSourceRef` is immutable) |
| `kopiur/snapshot` | Scheduled kopiur backups of an **existing** PVC the component does not own (`SnapshotPolicy` + `SnapshotSchedule`) into the `materia` repository. Parameterised by `APP`, `KOPIUR_SCHEDULE`, `KOPIUR_CACHE_CAPACITY`, `KOPIUR_PUID`/`KOPIUR_PGID` |
| `kopiur/secret` | The kopiur repository password (`kopiur-secret`) in a namespace, so that namespace's backup movers can open the `materia` ClusterRepository. Mixed into namespace-level kustomizations, not apps |
| `authentik-forward-auth` | Envoy `SecurityPolicy` forward-auth via Authentik for apps without native OIDC |
| `cnpg` | A CloudNativePG Postgres cluster for the app |
| `gpu` | Intel iGPU resource claims for transcoding workloads |
| `theme-park` | theme.park styling injection |
| `zeroscaler` | An HPA that scales the workload to zero when idle (uses the `HPAScaleToZero` feature gate) |

## Flux entrypoint

[`kubernetes/flux/cluster/ks.yaml`](../kubernetes/flux/cluster/ks.yaml) is the only
Kustomization the FluxInstance applies directly. It walks `kubernetes/apps` and patches
defaults into every child Kustomization/HelmRelease: drift detection enabled, CRDs
`CreateReplace`, rollback cleanup on failure (upgrade remediation is deliberately
unset — failed upgrades fail-and-hold for roll-forward). Any new `ks.yaml` under
`kubernetes/apps/**` inherits all of that for free.

`ksgate` (in `system/`) supplements `dependsOn` by gating Kustomizations on arbitrary
resource conditions.

## Talos configuration

```text
talos/
├── cluster.yaml.j2          # documents applied to every node (secrets via ref+op:// vals refs)
├── controlplane.yaml.j2     # control-plane-only documents, including machine.type
├── nodes/controlplane/      # per-node: install disk, links/bonds, hostname (+ optional
│                            #   <node>.schematic.yaml.j2 override — the VM node has one)
├── schematic.yaml.j2        # shared Image Factory schematic (baremetal)
└── README.md                # layering, merge rules, gotchas
```

Rendering is minijinja + `vals` (1Password resolution) driven by `just talos` recipes; a
node.s role is the directory its file lives in, and the three layers are merged by
`talosctl machineconfig patch` (cluster → role → node).
Disk roles are model-matched (`diskSelector` / `UserVolumeConfig`), so hardware swaps
mean updating a model string, not device paths.

## Bootstrap

Day-0 only — `just bootstrap cluster` drives Talos install, CRD seeding, and an ordered
helmfile chain (cilium → … → flux-instance) whose chart versions and values are read
from the same files Flux reconciles. Fully documented in [bootstrap.md](./bootstrap.md).

## Infrastructure (Ansible)

[`infrastructure/`](../infrastructure) manages the two Pi-holes: a `dnscrypt` play
(serial, one Pi at a time, with a resolve check) and an `observability` play. Secrets
come from 1Password via the `op` CLI. CI runs check mode on PRs and applies on merge —
see [cicd.md](./cicd.md).

## Conventions

- **Alphabetical ordering** in list-shaped files: kustomization `resources`/`components`,
  `ExternalSecret` `data:` entries, and similar. New entries go in their alphabetical
  slot, not at the end. Exception: functionally-ordered content (e.g. Authentik
  flow/binding blueprints where `order:` and `!KeyOf` references impose a sequence).
- **One 1Password item per app**, with multiple fields, consumed by a single
  `ExternalSecret`. Shared infra credentials (e.g. `ghcr-pull`) are the exception.
- **Schema headers** — every YAML file starts with a `yaml-language-server: $schema=`
  comment. CRD schemas are self-published to `schemas.materia.wtf` by
  `crd-schema-publisher`, so editors validate against exactly what the cluster runs.
- **Conventional Commits** on every commit (`feat(scope):`, `fix(scope):`, `chore:`…) —
  companion repos derive releases from them, and this repo's history stays greppable.
- **Git hooks** via lefthook, pulling the shared config from `home-operations/.github`.
- **Renovate config** lives in [`.renovaterc.json5`](../.renovaterc.json5), which
  extends the org preset `github>materia-ops/.github//renovate/default` and carries the
  auto-merge policy per dependency class. (A `.renovate/` directory is wired as an
  optional CI path trigger in the Renovate workflow but doesn't currently exist.)
