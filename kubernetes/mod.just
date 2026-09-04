set default-list
set default-script
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

[doc('Apply local Flux Kustomization')]
apply-ks ns ks:
    just kube render-local-ks "{{ ns }}" "{{ ks }}" | kubectl apply --server-side --force-conflicts --field-manager=kustomize-controller -f -

[doc('Browse a PVC')]
browse-pvc ns claim:
    kubectl browse-pvc -n {{ ns }} -i mirror.gcr.io/alpine:latest {{ claim }}

[doc('Debug a node')]
[script]
debug-node node:
    trap 'kubectl delete pod -n default -l app.kubernetes.io/managed-by=kubectl-debug --field-selector spec.nodeName={{ node }} --ignore-not-found --wait=false' EXIT
    kubectl debug node/{{ node }} -n default -it --image=mirror.gcr.io/alpine:latest --profile=sysadmin

[doc('Delete local Flux Kustomization')]
delete-ks ns ks:
    just kube render-local-ks "{{ ns }}" "{{ ks }}" | kubectl delete -f -

[doc('Open a shell on a node')]
[script]
node-shell node:
    kubectl debug node/{{ node }} -n default -it --image="mirror.gcr.io/alpine:latest" --profile sysadmin
    kubectl delete pod -n default -l app.kubernetes.io/managed-by=kubectl-debug

[doc('Force Flux to reconcile')]
reconcile:
    flux reconcile kustomization flux-system --with-source

[doc('Prune pods in Failed, Pending, or Succeeded state')]
[script]
prune-pods:
    for phase in Failed Pending Succeeded; do
        kubectl delete pods -A --field-selector status.phase="$phase" --ignore-not-found=true
    done

[doc('Restore a PVC from VolSync')]
[script]
restore ns app previous='0':
    flux -n {{ ns }} suspend kustomization {{ app }}
    flux -n {{ ns }} suspend helmrelease {{ app }}
    just kube quiesce "{{ ns }}" "{{ app }}"
    kubectl -n {{ ns }} get replicationdestination {{ app }}-dst -o json \
        | jq 'del(.status)
            | .metadata = {name: "{{ app }}-manual", namespace: .metadata.namespace}
            | .spec.kopia.copyMethod = "Direct"
            | .spec.kopia.destinationPVC = "{{ app }}"
            | .spec.kopia.previous = {{ previous }}' \
        | kubectl apply --server-side -f -
    kubectl -n {{ ns }} wait job/volsync-dst-{{ app }}-manual --for=create --timeout=120s
    kubectl -n {{ ns }} wait job/volsync-dst-{{ app }}-manual --for=condition=complete --timeout=120m
    kubectl -n {{ ns }} delete replicationdestination {{ app }}-manual
    flux -n {{ ns }} resume kustomization {{ app }}
    just kube unquiesce "{{ ns }}" "{{ app }}"

[doc('Force a VolSync Kopia repo maintenance pass (compaction + GC)')]
[script]
kopia-maintenance:
    # The shared Kopia repo needs periodic full maintenance or its index blobs
    # accumulate and every mover's connect slows down (index is read over NFS).
    # This triggers the existing daily maintenance CronJob now, as the repo's
    # maintenance owner (maintenance@volsync). Kopia has no lock to clear — this
    # is the recovery/optimize op (replaces the old restic `unlock` template).
    cronjob="$(kubectl -n volsync-system get cronjob -o name | grep -m1 kopia-maint)"
    job="kopia-maint-manual-$(date +%s)"
    kubectl -n volsync-system create job --from="$cronjob" "$job"
    kubectl -n volsync-system wait job/"$job" --for=condition=complete --timeout=60m
    kubectl -n volsync-system logs job/"$job" --tail=30

[doc('Snapshot VolSync PVCs')]
[script]
snapshot:
    kubectl get replicationsources --no-headers -A | while read -r ns name _; do
        kubectl -n "$ns" patch replicationsources "$name" --type merge -p '{"spec":{"trigger":{"manual":"$(date +%s)"}}}'
    done

[arg('state', pattern='suspend|resume')]
[doc('Suspend or resume VolSync')]
[script]
volsync state:
    flux -n volsync-system {{ state }} kustomization volsync
    flux -n volsync-system {{ state }} helmrelease volsync
    kubectl -n volsync-system scale deployment volsync --replicas {{ if state != "suspend" { "1" } else { "0" } }}

[doc('Show VolSync backup schedules')]
[script]
volsync-schedule:
    kubectl get replicationsources -A \
        -o custom-columns='NAMESPACE:.metadata.namespace,APP:.metadata.name,SCHEDULE:.spec.trigger.schedule,LAST_DURATION:.status.lastSyncDuration' \
        | (read -r header; echo "$header"; sort -k3)

[arg('resource', pattern='hr|ks|gitrepo|ocirepo|es')]
[doc('Sync a resource')]
[script]
sync resource:
    now=$(date +%s)
    kubectl get {{ resource }} --no-headers -A | while read -r ns name _; do
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite {{ resource }} "$name" \
            "force-sync=$now" \
            "reconcile.fluxcd.io/requestedAt=$now" \
            "reconcile.fluxcd.io/forceAt=$now"
    done

[doc('View a secret')]
view-secret ns secret:
    kubectl-view-secret -n "{{ ns }}" "{{ secret }}"

[doc('Snapshot a specific VolSync app')]
[script]
snapshot-app ns app:
    kubectl -n "{{ ns }}" patch replicationsources "{{ app }}" --type merge -p '{"spec":{"trigger":{"manual":"$(date +%s)"}}}'
    until kubectl -n "{{ ns }}" get job/volsync-src-"{{ app }}" &>/dev/null; do sleep 5; done
    kubectl -n "{{ ns }}" wait job/volsync-src-"{{ app }}" --for=condition=complete --timeout=120m

[doc('Snapshot a specific kopiur app now and wait for it')]
snapshot-kopiur ns app:
    kubectl kopiur -n "{{ ns }}" snapshot now --policy "{{ app }}" --wait --timeout 120m

[doc('Snapshot all kopiur apps now, one at a time')]
[script]
snapshot-kopiur-all:
    kubectl get snapshotpolicies.kopiur.home-operations.com --no-headers -A | while read -r ns name _; do
        just kube snapshot-kopiur "$ns" "$name"
    done

[doc('Kopiur flip step 1: suspend the app so its flip PR merges inertly')]
kopiur-flip-prepare ns app:
    flux -n {{ ns }} suspend kustomization {{ app }}
    flux -n {{ ns }} suspend helmrelease {{ app }}
    just log info "{{ app }} suspended. Merge its flip PR, then: just kube kopiur-flip {{ ns }} {{ app }}"

[doc('Kopiur flip step 2: snapshot, drop the VolSync PVC, repopulate from kopiur, restart')]
[script]
kopiur-flip ns app:
    # Preconditions first: the flip PR must already be applied to the (suspended) Kustomization spec.
    flux -n flux-system reconcile source git flux-system
    flux -n flux-system reconcile kustomization cluster-apps
    components="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.components}')"
    [[ "$components" == *kopiur/backup* && "$components" != *volsync* ]] \
        || { just log error "{{ app }}: Kustomization does not carry kopiur/backup without volsync; merge the flip PR first" components "$components"; exit 1; }
    want="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.postBuild.substitute.KOPIUR_CAPACITY}')"
    have="$(kubectl -n {{ ns }} get pvc {{ app }} -o jsonpath='{.spec.resources.requests.storage}')"
    [[ "${want:-5Gi}" == "$have" ]] \
        || { just log error "{{ app }}: KOPIUR_CAPACITY (${want:-5Gi}) does not match the live PVC ($have)"; exit 1; }
    # Warm snapshot while running, so the quiesced one below is a short incremental.
    just kube snapshot-kopiur "{{ ns }}" "{{ app }}"
    just kube quiesce "{{ ns }}" "{{ app }}"
    just kube snapshot-kopiur "{{ ns }}" "{{ app }}"
    # Keep the old RBD image (Released PV) as the rollback until the app checks out.
    pv="$(kubectl -n {{ ns }} get pvc {{ app }} -o jsonpath='{.spec.volumeName}')"
    kubectl patch pv "$pv" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
    kubectl -n {{ ns }} delete pvc {{ app }} --timeout=5m
    flux -n {{ ns }} resume kustomization {{ app }}
    just kube wait-restore "{{ ns }}" "{{ app }}" \
        || { just log error "{{ app }}: the populator Restore did not complete; HelmRelease left suspended, roll back from the retained PV" pv "$pv"; exit 1; }
    snap="$(kubectl -n {{ ns }} get restores.kopiur.home-operations.com/{{ app }} -o jsonpath='{.status.resolved.kopiaSnapshotID}')"
    [[ -n "$snap" ]] \
        || { just log error "{{ app }}: Restore completed WITHOUT a snapshot (empty volume); HelmRelease left suspended, roll back from the retained PV" pv "$pv"; exit 1; }
    kubectl -n {{ ns }} wait pvc/{{ app }} --for=jsonpath='{.status.phase}'=Bound --timeout=10m
    just kube unquiesce "{{ ns }}" "{{ app }}"
    just log info "{{ app }} is on kopiur; once the app checks out: kubectl delete pv $pv" snapshot "$snap" retained-pv "$pv"

[doc('Restore a kopiur app in place from its own SnapshotPolicy (0 = latest, 1 = previous, ...)')]
[script]
kopiur-restore ns app previous='0':
    # For apps already on components/kopiur/backup; the volsync `restore` recipe cannot
    # reach their data. Additive restore: files written since the snapshot survive.
    components="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.components}')"
    [[ "$components" == *kopiur/backup* ]] \
        || { just log error "{{ app }}: Kustomization does not carry kopiur/backup; volsync apps restore with just kube restore" components "$components"; exit 1; }
    # The one-off Restore inherits nothing from the policy, so mirror the app's own
    # mover identity and cache budget from the Kustomization it is rendered with.
    puid="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.postBuild.substitute.KOPIUR_PUID}')"
    pgid="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.postBuild.substitute.KOPIUR_PGID}')"
    cache="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.postBuild.substitute.KOPIUR_CACHE_CAPACITY}')"
    flux -n {{ ns }} suspend kustomization {{ app }}
    flux -n {{ ns }} suspend helmrelease {{ app }}
    # The mover has to mount the target PVC, so the app must be off it first.
    just kube quiesce "{{ ns }}" "{{ app }}"
    # A Restore pins its snapshot at admission, so a leftover from a previous run would
    # keep serving that snapshot (and its stale terminal status) under the new offset.
    kubectl -n {{ ns }} delete restores.kopiur.home-operations.com/{{ app }}-manual --ignore-not-found
    # onMissingSnapshot Fail: fromPolicy defaults to Continue, which would silently
    # "succeed" against nothing when the offset is past the end of the retention.
    kubectl apply --server-side -f - <<EOF
    ---
    apiVersion: kopiur.home-operations.com/v1alpha1
    kind: Restore
    metadata:
      name: {{ app }}-manual
      namespace: {{ ns }}
    spec:
      mover:
        cache:
          capacity: ${cache:-5Gi}
          contentCacheSizeMb: 2048
          metadataCacheSizeMb: 1024
          mode: Ephemeral
          storageClassName: openebs-hostpath
        podSecurityContext:
          fsGroup: ${pgid:-1000}
          fsGroupChangePolicy: OnRootMismatch
        securityContext:
          runAsGroup: ${pgid:-1000}
          runAsUser: ${puid:-1000}
      policy:
        onMissingSnapshot: Fail
      source:
        fromPolicy:
          name: {{ app }}
          offset: {{ previous }}
      target:
        pvcRef:
          name: {{ app }}
    EOF
    # Every failure below leaves the app suspended and the Restore in place, so
    # `kubectl -n {{ ns }} describe restore {{ app }}-manual` still explains itself.
    just kube wait-restore "{{ ns }}" "{{ app }}-manual"
    snap="$(kubectl -n {{ ns }} get restores.kopiur.home-operations.com/{{ app }}-manual -o jsonpath='{.status.resolved.kopiaSnapshotID}')"
    [[ -n "$snap" ]] \
        || { just log error "{{ app }}: Restore completed without resolving a snapshot; app left suspended"; exit 1; }
    kubectl -n {{ ns }} delete restores.kopiur.home-operations.com/{{ app }}-manual
    flux -n {{ ns }} resume kustomization {{ app }}
    just kube unquiesce "{{ ns }}" "{{ app }}"
    just log info "{{ app }} restored from kopiur at offset {{ previous }}" snapshot "$snap"

# kubectl wait on phase=Completed alone would sit out the whole timeout on a Failed
# restore — the case the caller most needs to hear about — so poll for either.
[private]
[script]
wait-restore ns name timeout='3600':
    kubectl -n {{ ns }} wait restores.kopiur.home-operations.com/{{ name }} --for=create --timeout=2m
    deadline=$((SECONDS + {{ timeout }}))
    while :; do
        phase="$(kubectl -n {{ ns }} get restores.kopiur.home-operations.com/{{ name }} -o jsonpath='{.status.phase}')"
        if [[ "$phase" == Completed ]]; then break; fi
        if [[ "$phase" == Failed ]]; then
            just log error "{{ name }}: Restore Failed" namespace "{{ ns }}"
            exit 1
        fi
        if (( SECONDS >= deadline )); then
            just log error "{{ name }}: Restore has not reached a terminal phase within {{ timeout }}s" phase "${phase:-Pending}"
            exit 1
        fi
        sleep 10
    done

# Every caller suspends the Kustomization and HelmRelease first, but that stops neither
# the HPA nor the CronJob controller. The zeroscaler HPA reverses the scale to 0 within a
# sync (Flux recreates it on resume); a CronJob pod — running, or kept by
# successfulJobsHistory — never leaves, so the wait below sits out its timeout and the
# PVC delete blocks on pvc-protection. Deleting the Jobs clears both.
[private]
quiesce ns app:
    kubectl -n {{ ns }} delete hpa {{ app }} --ignore-not-found
    kubectl -n {{ ns }} get cronjob -l app.kubernetes.io/name={{ app }} -o name \
        | xargs -r -I{} kubectl -n {{ ns }} patch {} -p '{"spec":{"suspend":true}}'
    kubectl -n {{ ns }} get deploy,sts -l app.kubernetes.io/name={{ app }} -o name \
        | xargs -r -I{} kubectl -n {{ ns }} scale {} --replicas=0
    kubectl -n {{ ns }} delete job -l app.kubernetes.io/name={{ app }}
    if kubectl -n {{ ns }} get pod -l app.kubernetes.io/name={{ app }} -o name | grep -q .; then \
        kubectl -n {{ ns }} wait pod --for=delete --selector="app.kubernetes.io/name={{ app }}" --timeout=5m; fi

[private]
unquiesce ns app:
    flux -n {{ ns }} resume helmrelease {{ app }}
    kubectl -n {{ ns }} get cronjob -l app.kubernetes.io/name={{ app }} -o name \
        | xargs -r -I{} kubectl -n {{ ns }} patch {} -p '{"spec":{"suspend":false}}'
    if kubectl -n {{ ns }} get deploy,sts -l app.kubernetes.io/name={{ app }} -o name | grep -q .; then \
        kubectl -n {{ ns }} wait pod --for=condition=ready --selector="app.kubernetes.io/name={{ app }}" --timeout=5m; fi

# flate comes from .mise/config.toml; CI's image-pull.yaml pins the same version.
[private]
render-local-ks ns ks:
    flate build ks --namespace "{{ ns }}" --path "{{ justfile_directory() }}/kubernetes" --output yaml "{{ ks }}"
