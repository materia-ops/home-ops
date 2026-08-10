<div align="center">

# ⛵ home-ops

_The **matalos** cluster — my home operations repository_

Talos Linux · Kubernetes · Flux · Renovate

</div>

---

## 📖 Overview

This repository holds the complete declarative state of my home infrastructure: a
3-node, highly available [Talos Linux](https://www.talos.dev/) Kubernetes cluster
reconciled by [Flux](https://fluxcd.io/) (flux-operator), plus the
[Ansible](./infrastructure) configuration for the supporting Raspberry Pi DNS hosts.
If it runs at home, it's defined here — Git is the cluster.

**Documentation lives in [`docs/`](./docs):**

| | |
| :--- | :--- |
| [Architecture](./docs/architecture.md) | Hardware, network topology, platform, storage, secrets, GitOps data flow |
| [Bootstrap](./docs/bootstrap.md) | Bare machines → Flux-managed cluster; reset and rebuild |
| [Repository structure](./docs/repo-structure.md) | Layout, app anatomy, components, conventions |
| [CI/CD](./docs/cicd.md) | Workflows, runners, Renovate, konflate, companion image repos |
| [Working in this repo](./docs/repo-workflow.md) | Change lifecycle, common tasks, keeping pipelines green |
| [Operations](./docs/operations.md) | Monitoring, reliability, scaling, deployment checklist |
| [Disaster recovery](./docs/disaster-recovery.md) | Total-loss runbook: reset → bootstrap → Flux → data restore |

## 🖥️ Hardware

| Device | Description | Role |
| :--- | :--- | :--- |
| `matalos-c1` | VM (8 vCPU / 32 GB) on `pve-0` — Supermicro X10SDV (Xeon D-1520, 128 GB ECC) | Control plane + worker |
| `matalos-c2` | Lenovo ThinkStation P330 Tiny — i7-8700, 32 GB | Control plane + worker |
| `matalos-c3` | Lenovo ThinkStation P330 Tiny — i7-8700, 32 GB | Control plane + worker |
| NAS | TrueNAS SCALE VM on `pve-0` (4 vCPU / 64 GB) — 6 × 28 TB Exos + 2 × DC S3700 400 GB | NFS media + Kopia backup target |
| `pi-0` | Raspberry Pi 5 16 GB (Argon ONE V3, KC3000 NVMe) | Pi-hole + dnscrypt DNS |
| `pi-1` | Raspberry Pi 4 8 GB (Argon ONE) | Pi-hole + dnscrypt DNS |
| `pikvm` | PiKVM | Out-of-band console |

Each node carries a dedicated Micron 7450 960 GB NVMe for Ceph and a Corsair MP600
Mini 1 TB for local hostpath storage. Networking is UniFi end-to-end: UDM Pro
(Aussie Broadband WAN) → USW Aggregation (10 GbE core) → USW Pro Max 24 PoE, with LACP
bonds to the nodes and NAS, and U7 Pro Max / U6 Mesh for Wi-Fi. The UDM Pro peers with
Cilium over BGP to route LoadBalancer VIPs.

## 🧱 Stack

| | Component | Purpose |
| :--- | :--- | :--- |
| 🐧 | [Talos Linux](https://www.talos.dev/) | Immutable, API-driven Kubernetes OS |
| 🔄 | [Flux](https://fluxcd.io/) (flux-operator) | GitOps reconciliation with drift detection + self-healing |
| 🕸️ | [Cilium](https://cilium.io/) | CNI, kube-proxy replacement, BGP load-balancer VIPs |
| 🌐 | [Envoy Gateway](https://gateway.envoyproxy.io/) | Gateway API ingress — internal, external, and TLS gateways |
| ☁️ | [Cloudflare](https://www.cloudflare.com/) + cloudflared | Public DNS + tunnel for external apps |
| 🔍 | [external-dns](https://github.com/kubernetes-sigs/external-dns) ×3 + [k8s-gateway](https://github.com/ori-edge/k8s_gateway) | DNS records in Cloudflare, UniFi, and Pi-hole; split-horizon DNS |
| 🗄️ | [Rook-Ceph](https://rook.io/) / [OpenEBS](https://openebs.io/) / NFS | Replicated block, local hostpath, bulk media |
| 💾 | [VolSync](https://volsync.readthedocs.io/) + [Kopia](https://kopia.io/) | Scheduled PVC backups to the NAS, one-command restore |
| 🔐 | [External Secrets](https://external-secrets.io/) + [1Password Connect](https://developer.1password.com/docs/connect/) | Secrets from 1Password, none in Git |
| 🛡️ | [Authentik](https://goauthentik.io/) | SSO — OIDC + Envoy forward-auth, blueprint-managed |
| 📈 | [VictoriaMetrics](https://victoriametrics.com/) / VictoriaLogs / [Grafana](https://grafana.com/) | Metrics (90 d), logs, dashboards-as-code, Pushover alerting |
| 🤖 | [Renovate](https://www.mend.io/renovate) + [konflate](https://github.com/home-operations) | Automated updates; rendered Flux diffs as PR checks |
| 🏃 | [ARC](https://github.com/actions/actions-runner-controller) | Self-hosted GitHub runners in-cluster (image pre-pull, Ansible) |
| ⬆️ | tuppr + [Spegel](https://spegel.dev/) | Automated Talos/K8s upgrades; P2P registry mirror |

## 📁 Layout

```text
├── kubernetes/
│   ├── apps/          # one directory per namespace, one per app (ks.yaml + app/)
│   ├── components/    # reusable Kustomize components (volsync, alerts, sso, …)
│   ├── flux/cluster/  # the single Flux entrypoint
│   └── templates/     # legacy VolSync restore template (unused since the Kopia migration)
├── talos/             # machine config templates (minijinja + 1Password refs)
├── bootstrap/         # day-0 helmfile bring-up (CRDs → core apps → Flux)
├── infrastructure/    # Ansible for the Pi-hole hosts
└── docs/              # documentation
```

## 🙏 Thanks

Based on [onedr0p/cluster-template](https://github.com/onedr0p/cluster-template) and
shaped by the [Home Operations](https://discord.gg/home-operations) community and the
[home-operations](https://github.com/home-operations) projects.
