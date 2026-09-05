# Working in this Repository

The contract for making changes so that every pipeline stays green and Flux does what
you expect. Pipelines themselves are documented in [cicd.md](./cicd.md).

## Golden rules

1. **Git is the cluster.** Never make a persistent change with `kubectl` — drift
   detection reverts it on the next reconcile. `kubectl` is for reading and debugging.
2. **Everything goes through a PR to `main`.** The PR checks (konflate diff, Image
   Pull) are the safety net; pushing straight to `main` skips them.
3. **Conventional Commits, always** — `feat(scope):`, `fix(scope):`, `chore(scope):`.
   Companion repos cut releases from these; this repo's tags and history depend on them.
4. **Secrets never touch Git.** New secret material goes into 1Password (one item per
   app); the repo only ever references it (`ExternalSecret` in-cluster, `ref+op://` in
   Talos/bootstrap templates).
5. **Alphabetical ordering** in resource lists, `ExternalSecret` data, and similar —
   insert new entries in their slot (see [repo-structure.md](./repo-structure.md#conventions)).

## Environment setup

```sh
mise trust && mise install   # installs pinned talosctl, flux, kubectl, helmfile, just, …
just                         # lists available recipes (bootstrap, kube, talos modules)
```

`mise` also wires `KUBECONFIG`/`TALOSCONFIG` to the repo-local files and loads
`.secrets.env`. Git hooks come from lefthook (`.lefthook.toml`).

## The change lifecycle

```text
branch → commit (conventional) → PR → checks → merge → Flux deploys
```

1. **Branch and edit.** Keep the YAML schema header comments intact — they're how the
   editor validates against the cluster's actual CRD versions.
2. **Open the PR.** Watch for:
   - **konflate** comments the rendered Flux diff — *read it*; it's the ground truth of
     what will change in the cluster, including effects of shared components you may
     not have touched directly.
   - **Image Pull** pre-warms any changed images onto the nodes. A failure here usually
     means a typo'd image reference — fix it before merge, not after.
   - **Validate (Syntax Check)** (only when `infrastructure/**` changed) checks the
     playbook without credentials; the live `--check` dry-run runs post-merge, gating
     the apply.
3. **Merge.** The GitHub webhook triggers Flux within seconds. If you're impatient or
   the webhook misfires: `just kube reconcile`.
4. **Verify.** `flux get ks -A --status-selector ready=false` and
   `flux get hr -A --status-selector ready=false` should both come back empty; a failed
   HelmRelease will also fire a Pushover alert via Alertmanager.

## Common tasks

### Adding a new app

1. Create `kubernetes/apps/<namespace>/<app>/` with `ks.yaml` + `app/` following an
   existing app in the same namespace (see
   [repo-structure.md](./repo-structure.md#anatomy-of-an-app)).
2. Add the app to the namespace `kustomization.yaml` (alphabetical slot).
3. Opt into components in `ks.yaml`: `kopiur/backup` if it has state (set
   `KOPIUR_CAPACITY`; `KOPIUR_SCHEDULE` defaults to `H * * * *`, which kopiur staggers on
   its own), `alerts`, `authentik-forward-auth` if it needs SSO without native OIDC, etc.
4. Secrets: create the 1Password item, add an `externalsecret.yaml`.
5. Routing: `httproute.yaml` against `envoy-internal` (LAN-only) or `envoy-external`
   (public via the tunnel). external-dns handles the records.
6. If the app is behind Authentik forward-auth in a **new namespace**, add the
   namespace to Authentik's ReferenceGrant/SecurityPolicy wiring — otherwise the
   SecurityPolicy silently fails **open** (no SSO).

### Handling Renovate PRs

- Auto-merged classes (mise minor/patch, trusted digests, own images) need no action —
  but a red auto-merge PR is a signal something upstream broke; investigate rather than
  force it.
- For chart **major** versions, read the upstream changelog; the konflate diff shows the
  rendered effect of values-schema changes.
- Some pins are deliberate — check for Renovate constraints/comments before "helpfully"
  merging a held-back update (e.g. MySQL is pinned `<9`; the iGPU nodes are i915-only,
  so driver-related bumps that assume `xe` don't apply).

### Changing PVC capacity

Change `KOPIUR_CAPACITY` in the app's `ks.yaml`; the `kopiur/backup` component owns the
PVC and sizes it from that value. The kopia mover cache is `Ephemeral` and sized separately
by `KOPIUR_CACHE_CAPACITY`, so there is no cache PVC to clean up.

### Restoring app data

```sh
just kube kopiur-restore <namespace> <app> [previous]
```

It suspends Flux for the app, scales it down, restores from the `materia` repository on the
NAS (`/mnt/apps/kopiur`) into the app PVC, then resumes Flux and waits for the pod to come
back Ready. Browse any PVC with `just kube browse-pvc <ns> <claim>`.

### Talos / Kubernetes changes

```sh
just talos apply-node matalos-c2      # after editing talos/ templates
just talos upgrade-node matalos-c2    # Talos version bump
just talos upgrade-k8s <version>      # Kubernetes version bump
```

Version bumps also arrive as Renovate PRs and are orchestrated in-cluster by tuppr.
Some machine-config changes only take effect with an upgrade, not just an apply.

### Infrastructure (Pi-hole) changes

Edit under `infrastructure/`, open a PR — CI syntax-checks the playbook (PRs never
reach the self-hosted runners); on merge, check mode runs against the live Pis and
then the apply, one Pi at a time. For an ad-hoc scoped run use the workflow's manual
dispatch (`tags`, `limit`, `check_only`).

### Companion-repo changes (azerothcore-image, wow-panel, raidscope)

Work lands there first; home-ops only merges the resulting image bump.

- **azerothcore-image build-input PRs: open as draft → mark ready for ONE trial build →
  wait for green → merge.** Merging promotes the trial image by digest (~3 min);
  merging mid-build triggers a full ~2 h rebuild. Rebase the PR if `main` moved.
- Release PRs (release-please) are merged by a human; the image publish then
  auto-notifies home-ops Renovate (`repository_dispatch`), so the bump PR appears within
  a minute — no manual bumping.
- If a promotion spans multiple concerns (new module + its conf + a pin), bundle them in
  one home-ops PR so Flux applies them atomically.

## Debugging a failed deploy

```sh
flux get ks -A            # which Kustomization is stuck
flux get hr -A            # which HelmRelease failed
kubectl -n <ns> describe helmrelease <app>
kubectl -n <ns> get events --sort-by=.metadata.creationTimestamp
kubectl -n <ns> logs deploy/<app> -f
just kube debug-node <node>    # privileged shell on a node when it's host-level
```

If an upgrade was interrupted and Helm is stuck in a rollback loop against a
forward-migrated database, **roll forward**:
`flux reconcile hr <app> -n <ns> --reset --force` — never roll back over a completed DB
migration.
