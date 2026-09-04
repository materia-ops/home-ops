# Operations

Monitoring, reliability, scaling, and the production deployment checklist for the
matalos cluster.

## Monitoring and logging

The observability stack lives in the `o11y` namespace, built on VictoriaMetrics rather
than kube-prometheus-stack:

| Concern | Component | Notes |
| :--- | :--- | :--- |
| Metrics TSDB | VictoriaMetrics (`vmsingle`) | 90-day retention, 50 Gi on `ceph-block` |
| Scraping | `vmagent` + prometheus-operator CRDs | Apps expose `ServiceMonitor`/`PodMonitor`; the operator CRDs are installed standalone |
| Alert evaluation | `vmalert` | `PrometheusRule` CRs, colocated with apps in their directories |
| Alert delivery | Alertmanager → **Pushover** | Flux reconciliation errors route here too (notification-controller → Alertmanager provider) |
| Alert hygiene | silence-operator | Declarative, Git-managed silences |
| Logs | VictoriaLogs | Cluster log aggregation |
| Dashboards | Grafana (grafana-operator) | Dashboards as `GrafanaDashboard` CRs next to the app that owns them |
| Uptime / synthetic | gatus-sidecar (bundles gatus) | Endpoints declared via `gatus.home-operations.com/endpoint` annotations on HTTPRoutes; external checks resolve via public DNS (`1.1.1.1`) so they test the real public path |
| Blackbox probes | blackbox-exporter | ICMP/TCP/HTTP probes for non-cluster targets |
| Hardware | smartctl-exporter, node-exporter, drm-exporter (iGPU) | Disk health, node metrics, GPU utilisation |
| Network gear | unpoller | UniFi controller metrics |
| Pi-holes | Ansible `observability` play | Exporters on `pi-0`/`pi-1` feed the same stack |

**Strategy:** every app ships its own monitors, rules, and dashboards in its own
directory (the standard app pattern), so observability arrives with the deployment
rather than being retrofitted. Alerting is push-based (Pushover) with two independent
sources — metric alerts via vmalert and GitOps failures via Flux notifications — so a
broken deploy pages even when the metrics path is what broke.

## Reliability

Defence in depth, roughly outermost-in:

- **HA control plane** — 3 etcd members; any single node can fail. `matalos-c1` runs on
  different hardware (Proxmox VM on the Xeon-D host) than the two P330 Tinys, so a
  model-specific fault can't take all three.
- **GitOps self-healing** — Flux drift detection re-applies manual/mutated state; a
  failed HelmRelease upgrade cleans up, stops, and alerts (fail-and-hold — upgrade
  remediation is deliberately unset so DB-migrating apps are never auto-rolled-back;
  recovery is roll-forward). The cluster converges on Git even after operator mistakes.
- **Rollout safety** — CI pre-pulls changed images to every node before merge; Spegel
  P2P-mirrors images between nodes, so workloads reschedule even during a registry
  outage; Reloader restarts pods when their ConfigMaps/Secrets rotate.
- **Storage** — Ceph replicates across the three NVMe OSDs (one per node); a node
  failure keeps every `ceph-block` PVC available.
- **Backups** — kopiur snapshots every stateful app into the `materia` Kopia repository on
  the NAS on its own schedule; snapshot on demand with `just kube snapshot-kopiur` and
  restore with `just kube kopiur-restore`. MySQL (AzerothCore) additionally dumps ahead of
  snapshots.
- **DNS resilience** — two Pi-holes on separate Pis; Ansible rolls DNS changes
  one Pi at a time with a resolve check between hosts.
- **Node-level** — hardware watchdog (5 min) reboots a hung node; the descheduler
  rebalances after disruptions; scheduler topology-spread defaults keep replicas off a
  single node.
- **Out-of-band access** — PiKVM for console access when a node won't boot; Talos can
  always be re-driven from this repo (`just talos apply-node`).

### Known failure modes and their runbooks

- **Interrupted Helm upgrade after a DB migration** → rollback loop on the old image.
  Roll **forward** (`flux reconcile hr --reset --force`); never roll back over a
  completed migration.
- **App boots on an empty volume after node disruption** (looks wiped) → usually a
  stale ceph-csi staging path making kubelet skip NodeStage; data is intact. Scale to
  zero, clean the stale staging dirs from a node debug pod, restart kubelet.
- **PVC capacity bump** → bump `KOPIUR_CAPACITY` in the app's `ks.yaml`; the mover cache is
  `Ephemeral` and sized separately, so there is no cache PVC to clean up.

## Scaling

Vertical headroom is the primary axis (32 GB/node, NVMe-backed everything); the
automation in place:

- **Scale-to-zero** — the `zeroscaler` component (HPA + `HPAScaleToZero` feature gate)
  parks idle workloads at 0 replicas; prometheus-adapter feeds custom metrics.
- **CI runners** — ARC scales `home-ops-runner` 0→3 with queue depth (no warm runner
  holds the Talos `os:admin` identity between jobs).
- **Adding a node** — one new file in `talos/nodes/<role>/`, a switch port trunked for
  VLANs 20/70/90, and `just talos apply-node`; Ceph picks up a Micron 7450 OSD via the
  model filter automatically.
- **Network** — 10 GbE core (aggregation switch, LACP everywhere) means east-west
  replication (Ceph, Spegel) isn't bottlenecked by node links.

## Production deployment checklist

For routine changes the PR checks are the checklist. For **significant** changes
(stateful apps, storage, networking, Talos, anything with a migration):

**Before merge**

- [ ] konflate diff read and matches intent — no surprise deletions or unrelated churn
- [ ] Image Pull check green (images exist and are pullable)
- [ ] Stateful app? Confirm a fresh snapshot exists (or trigger one with `just kube
      snapshot-kopiur`) before a risky upgrade
- [ ] DB migration in the release? Plan is roll-forward; don't merge right before
      walking away
- [ ] New namespace behind forward-auth? Authentik ReferenceGrant/SecurityPolicy updated
      (fails open otherwise)
- [ ] Renovate majors: upstream changelog read, values schema changes accounted for
- [ ] Networking/VLAN changes: switch ports stay trunked (native 20, tagged 70/90)

**After merge**

- [ ] Flux reconciled clean: `flux get ks -A` / `flux get hr -A` show Ready
- [ ] Workload healthy: pods running, no CrashLoopBackOff, logs sane
- [ ] Route reachable (internal and/or public per gateway); gatus goes green
- [ ] No new alerts after ~15 minutes (Pushover quiet, vmalert clean)
- [ ] For storage/Talos changes: `ceph status` HEALTH_OK, all nodes Ready

**Rollback triggers** — an upgrade that stays failed, data-integrity doubt, or a
red gatus endpoint that won't recover: revert the Git commit (Flux converges back), or
for migrated databases roll forward per the runbook above.
