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

[doc('Snapshot a specific kopiur app now and wait for it')]
snapshot-kopiur ns app:
    kubectl kopiur -n "{{ ns }}" snapshot now --policy "{{ app }}" --wait --timeout 120m

[doc('Snapshot all kopiur apps now, one at a time')]
[script]
snapshot-kopiur-all:
    kubectl get snapshotpolicies.kopiur.home-operations.com --no-headers -A | while read -r ns name _; do
        just kube snapshot-kopiur "$ns" "$name"
    done

[doc('Restore a kopiur app in place from its own SnapshotPolicy (0 = latest, 1 = previous, ...)')]
[script]
kopiur-restore ns app previous='0':
    # Additive restore: files written since the snapshot survive.
    components="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.components}')"
    [[ "$components" == *kopiur/backup* ]] \
        || { just log error "{{ app }}: Kustomization does not carry kopiur/backup, so the app has no snapshots to restore" components "$components"; exit 1; }
    # the one-off Restore inherits nothing from the policy
    puid="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.postBuild.substitute.KOPIUR_PUID}')"
    pgid="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.postBuild.substitute.KOPIUR_PGID}')"
    cache="$(kubectl -n {{ ns }} get kustomization {{ app }} -o jsonpath='{.spec.postBuild.substitute.KOPIUR_CACHE_CAPACITY}')"
    flux -n {{ ns }} suspend kustomization {{ app }}
    flux -n {{ ns }} suspend helmrelease {{ app }}
    # The mover has to mount the target PVC, so the app must be off it first.
    just kube quiesce "{{ ns }}" "{{ app }}"
    # a Restore pins its snapshot at admission, so a leftover would serve the old one
    kubectl -n {{ ns }} delete restores.kopiur.home-operations.com/{{ app }}-manual --ignore-not-found
    # onMissingSnapshot Fail: the default Continue "succeeds" against nothing
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
    # failures below deliberately leave the app suspended and the Restore in place
    just kube wait-restore "{{ ns }}" "{{ app }}-manual"
    snap="$(kubectl -n {{ ns }} get restores.kopiur.home-operations.com/{{ app }}-manual -o jsonpath='{.status.resolved.kopiaSnapshotID}')"
    [[ -n "$snap" ]] \
        || { just log error "{{ app }}: Restore completed without resolving a snapshot; app left suspended"; exit 1; }
    kubectl -n {{ ns }} delete restores.kopiur.home-operations.com/{{ app }}-manual
    flux -n {{ ns }} resume kustomization {{ app }}
    just kube unquiesce "{{ ns }}" "{{ app }}"
    just log info "{{ app }} restored from kopiur at offset {{ previous }}" snapshot "$snap"

# poll for either terminal phase: waiting on Completed alone sits out the whole
# timeout when the Restore has already Failed
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

# Suspending Flux stops neither the zeroscaler HPA nor the CronJob controller: the HPA
# reverses the scale and a leftover CronJob pod holds the PVC open.
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

# Resume alone does not restore the replica count (drift correction is not guaranteed), and
# `wait --for=condition=ready` exits 1 before the controller has made a Pod.
[private]
unquiesce ns app:
    flux -n {{ ns }} resume helmrelease {{ app }}
    kubectl -n {{ ns }} get cronjob -l app.kubernetes.io/name={{ app }} -o name \
        | xargs -r -I{} kubectl -n {{ ns }} patch {} -p '{"spec":{"suspend":false}}'
    kubectl -n {{ ns }} get deploy,sts -l app.kubernetes.io/name={{ app }} -o name \
        | xargs -r -I{} kubectl -n {{ ns }} scale {} --replicas=1
    kubectl -n {{ ns }} get deploy,sts -l app.kubernetes.io/name={{ app }} -o name \
        | xargs -r -I{} kubectl -n {{ ns }} rollout status {} --timeout=5m

# flate comes from .mise/config.toml; CI's image-pull.yaml pins the same version.
[private]
render-local-ks ns ks:
    flate build ks --namespace "{{ ns }}" --path "{{ justfile_directory() }}/kubernetes" --output yaml "{{ ks }}"
