# home-ops — contributor/session instructions

Flux GitOps monorepo for the Materia Talos Kubernetes cluster. Everything
merged here reconciles onto a live cluster: the default posture is small,
reviewable, reversible changes. This repo is PUBLIC — no secrets in git,
ever; secrets flow through ExternalSecrets (one 1Password item per app).

## Shared checkout — never do branch work here

A checkout of this repo may be shared by several concurrent working
sessions. Git branch, index, and working-tree state are per-checkout, not
per-session — a `git checkout` in one session silently moves HEAD under
every other one, and commits pick up whatever is in the shared index.

- Never run `git commit`, `checkout`, `switch`, `reset`, `rebase`, or
  `merge` in the main checkout. It stays on `main` and only moves by
  `git pull`.
- ALL branch work happens in an isolated worktree:
  `git worktree add <scratchpad>/wt-<topic> -b <branch> origin/main`.
  Edit, commit, and push from the worktree; remove it
  (`git worktree remove <path>`) once the PR is open.
- Foreign dirty files or an unexpected branch mean another session is
  mid-flight: leave its state alone and report it.

## Commit / PR style

Conventional Commits (`type(scope):`) on every commit; PRs are opened
with `gh pr create` and merged by the maintainer, not by sessions.

## Layout

- `kubernetes/apps/<namespace>/<app>/` — workloads;
  `kubernetes/{flux,components,templates}/` — shared machinery;
  `talos/`, `bootstrap/`, `infrastructure/` (ansible).
- `docs/` — committed public docs (start at docs/README.md). Work
  notes live in the private materia-vault (below), never in this repo.

## Conventions

- Alphabetical ordering everywhere order isn't functional (kustomization
  `resources:`, ExternalSecret `data:`, env lists): insert new entries in
  their slot, never append. Exception: Authentik flow/stage/policy/
  binding blueprints are order-load-bearing (`!KeyOf` requires the
  referenced entry earlier in the file) — never reorder those.
- New apps copy the pattern of a recently-added neighbor app, not an old
  outlier.

## Cluster-safety rules

- Sessions change the cluster via PRs + Flux, not kubectl — no live
  kubectl/flux mutations unless the task explicitly asks for them.
- NEVER `kubectl delete --force --grace-period=0` a stateful pod:
  preStop hooks (e.g. the game server's world save) must finish.
- The backup component OWNS the `${APP}` PVC — `volsync` today,
  `kopiur/backup` for migrated apps. Never declare a second PVC and never
  mix the two on one app. volsync: cacheCapacity must stay >=
  VOLSYNC_CAPACITY on size bumps. kopiur: KOPIUR_CAPACITY sizes the PVC
  and KOPIUR_CACHE_CAPACITY is deliberately independent of it.
- A kopiur flip PR (an app's ks swapping to `components/kopiur/backup`)
  merges ONLY after `just kube kopiur-flip-prepare <ns> <app>` has
  suspended the app — merged unsuspended it wedges the Kustomization on
  the PVC's immutable dataSourceRef. Runbook: the migration plan in
  materia-vault.
- Flux Kustomizations with `substitute: disabled` skip `${VAR}`
  substitution — check before relying on variables in that app.
- app-template 5.x needs `createDefaultServiceAccount: false` plus an
  explicit rbac ServiceAccount.
- MySQL is pinned to 8.4 LTS: never bump the major, never automerge
  database images.

## Definition of done

1. `just kube render-local-ks <ns> <ks>` (flate) renders clean for every
   affected app. `kustomize build` is only a rough fallback — it can't
   resolve Flux substitutions, so a clean run proves less than flate.
2. Conventions held (alphabetical ordering, neighbor-pattern layout,
   substitution rules).
3. Read the konflate rendered-diff comment on the PR — it is the ground
   truth for what actually reconciles; confirm it matches intent.
4. PR describes what changes on the cluster when it reconciles —
   behavior before vs after, not just which files moved — how it was
   validated, and a rollback note for anything stateful.

## Work docs

Code-describing docs (architecture, CI, troubleshooting) live in this
repo. Work-describing docs — decisions, plans, handovers, reviews,
prompts, anything cross-repo — live in the private
`materia-ops/materia-vault` Obsidian vault; its root CLAUDE.md holds
the note contract.
