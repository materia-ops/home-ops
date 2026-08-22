# Contributing

First, honest framing: this is a **personal home-lab cluster repository**. Everything
merged here reconciles onto a live cluster in my house, so PRs from outside are not
really solicited — there is no way to test a change except against my hardware. The
repo is public because reading other people's GitOps repos is how this one got built.

That means the most useful ways to "contribute" are:

- **Fork and adapt it** for your own cluster (guide below).
- **Open an issue** if you spot something broken, insecure, or misleading in the docs.
- If you do open a PR (typo fixes, doc corrections), follow the norms at the bottom.

## Fork-and-adapt guide

If you want to reuse this repo, it will not work as-is — it is wired to my org, my
domain, my 1Password account, and my network. This repo itself started from
[onedr0p/cluster-template](https://github.com/onedr0p/cluster-template), which is the
better starting point for a brand-new cluster; fork this one if you specifically want
its patterns. Either way, here is everything you must change:

| What | Where it lives |
| :--- | :--- |
| **Org/repo name** (`materia-ops/home-ops`) | The `FluxInstance` GitRepository URL ([`kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml`](./kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml)), konflate's `github://` repo ([`kubernetes/apps/flux-system/konflate/app/helmrelease.yaml`](./kubernetes/apps/flux-system/konflate/app/helmrelease.yaml)), the Renovate org preset in [`.renovaterc.json5`](./.renovaterc.json5), and the workflows under [`.github/workflows/`](./.github/workflows) |
| **Domain** (`materia.wtf`) | HTTPRoutes, gatus endpoint annotations, external-dns, split-DNS config, and the `schemas.materia.wtf` YAML schema headers on every manifest — grep for `materia.wtf` and replace with your own domain (Cloudflare-managed if you keep the tunnel + external-dns setup) |
| **1Password wiring** | The mechanism, not the values: External Secrets Operator + [1Password Connect](https://developer.1password.com/docs/connect/), one 1Password item per app in a `kubernetes` vault, consumed by each app's `externalsecret.yaml`. Bootstrap seeds exactly three secrets from your workstation (the two Connect credential secrets and a Cloudflare tunnel ID — see [docs/bootstrap.md](./docs/bootstrap.md)); everything in [`talos/`](./talos) and [`bootstrap/`](./bootstrap) resolves `ref+op://` references via `vals` and your local `op` session. You need your own vault, Connect credentials, and service accounts — or swap in a different ESO provider |
| **Node IPs, VLANs, BGP ASNs, hardware** | Documented in [docs/architecture.md](./docs/architecture.md); declared in [`talos/`](./talos) (`cluster.yaml.j2` + `controlplane.yaml.j2`, per-node files under `nodes/<role>/`, the Image Factory schematic, disk-model selectors) and in the Cilium app's BGP peering + LB pool config. Replace with your own addressing and router — the BGP peering assumes a UniFi UDM Pro |
| **Local secret files** | `talosconfig`, `kubeconfig`, and `.secrets.env` are gitignored and machine-generated — you create your own; never commit them |
| **Private images** | Some apps consume private `ghcr.io/materia-ops/*` images built by companion repos (see [docs/cicd.md](./docs/cicd.md)) — you can't pull these; drop those apps or point them at your own builds |

> [!IMPORTANT]
> This repo is public and contains **no secrets** — everything sensitive flows through
> ExternalSecrets or `ref+op://` references. Keep it that way in your fork: one leaked
> commit is forever.

## Norms for changes (mine and yours)

These are the actual conventions enforced in this repo — see
[docs/repo-structure.md](./docs/repo-structure.md#conventions) and
[docs/repo-workflow.md](./docs/repo-workflow.md):

- **Conventional Commits** on every commit (`feat(scope):`, `fix(scope):`, `chore:` …).
- **Alphabetical ordering** in list-shaped files (kustomization `resources:`,
  `ExternalSecret` `data:`, env lists) — new entries go in their slot, not at the end.
  Exception: functionally-ordered content such as Authentik blueprints, where order is
  load-bearing.
- **Schema headers** — every YAML file keeps its `yaml-language-server: $schema=`
  comment.
- **Everything through a PR to `main`** — the konflate diff and Image Pull checks are
  the safety net; PRs are merged by the maintainer.
- New apps copy the pattern of a recently-added neighbouring app.
- `kustomize build` must run clean on every affected path.
