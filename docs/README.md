# Documentation

Documentation for the **matalos** cluster and this repository.

| Document | Covers |
| :--- | :--- |
| [architecture.md](./architecture.md) | System architecture — hardware, network topology, Kubernetes platform, storage, secrets, and the GitOps data flow |
| [bootstrap.md](./bootstrap.md) | Bootstrap — from bare machines to a Flux-managed cluster: Talos install, the `just bootstrap cluster` pipeline, handoff to Flux, reset/rebuild |
| [repo-structure.md](./repo-structure.md) | Component structure — how the repository is laid out, the anatomy of an app, reusable components, and repo conventions |
| [cicd.md](./cicd.md) | CI/CD — every GitHub Actions workflow, the self-hosted runners, Renovate, konflate PR gating, and the companion image-repo pipelines |
| [repo-workflow.md](./repo-workflow.md) | How to interact with the repository — the change lifecycle, keeping the pipelines green, adding apps and secrets, and upgrade procedures |
| [operations.md](./operations.md) | Operations — monitoring and logging strategy, reliability, scaling, backup/restore, and the production deployment checklist |
| [disaster-recovery.md](./disaster-recovery.md) | Disaster recovery — the ordered total-loss runbook: node reset/reimage, `just bootstrap cluster`, Flux convergence, and kopiur/Kopia data restore |

## Scope notes

This is a GitOps repository: the "application" is the cluster itself, expressed as
declarative Talos, Kubernetes, and Ansible configuration. A few document types that a
conventional application repo would carry are intentionally **not** here:

- **API design** — the repo exposes no bespoke API. The APIs in play are Kubernetes,
  Talos, and the Flux CRDs, all documented upstream. Applications with their own APIs
  (wow-panel, raidscope) document them in their own repositories.
- **Database schema** — databases are per-application implementation details
  (CloudNativePG operator in `database/`, MySQL for AzerothCore in `games/`). Their
  schemas are owned by the upstream applications, not by this repo.
- **Caching strategy** — there is no application cache tier to design. The caching that
  exists (Spegel P2P image mirroring, CI image pre-pull, kubelet image GC tuning) is
  covered in [architecture.md](./architecture.md) and [cicd.md](./cicd.md).
- **Implementation code** — the manifests *are* the implementation; there is no
  separate application codebase in this repo.
