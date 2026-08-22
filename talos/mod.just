set default-list
set default-script
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

[confirm('Apply Talos config to ' + node + ' [y|N] ?')]
[doc('Apply Talos config to a node')]
apply-node node *args:
    just talos render-config "{{ node }}" | talosctl -n "{{ node }}" apply-config -f /dev/stdin {{ args }}

[doc('Download Talos machine image (iso=true bakes the static bond/ip args for baremetal installs)')]
download-image node version iso="false":
    export SCHEMATIC="$(just talos schematic-id "{{ node }}" "{{ iso }}")"
    curl -fL --remove-on-error --retry 5 --retry-delay 5 --retry-all-errors --progress-bar \
        -o "{{ source_directory() }}/talos-{{ version }}-${SCHEMATIC:0:8}.iso" \
        "https://factory.talos.dev/image/${SCHEMATIC}/{{ version }}/metal-amd64.iso"
    just log info "Downloaded Talos" version "{{ version }}" schematic "${SCHEMATIC}"

[doc('Generate kubeconfig for the cluster')]
[private]
generate-kubeconfig:
    talosctl kubeconfig -n "$(talosctl config info -o yaml | yq -e '.endpoints[0]')" -f --force-context-name main {{ justfile_dir() }}

[confirm('Reboot node ' + node + ' [y|N] ?')]
[doc('Reboot a node')]
reboot-node node:
    talosctl -n {{ node }} reboot -m powercycle

[doc('Render Talos config for a node')]
render-config node:
    schematic="$(just talos schematic-id "{{ node }}")"
    role="$(just talos node-role "{{ node }}")"
    talosctl machineconfig patch <(just template "{{ source_directory() }}/cluster.yaml.j2" -D "schematic=${schematic}") \
        -p @<(just template "{{ source_directory() }}/${role}.yaml.j2") \
        -p @<(just template "{{ source_directory() }}/nodes/${role}/{{ node }}.yaml.j2" -D "schematic=${schematic}")

[confirm('Reset node ' + node + ' [y|N] ?')]
[doc('Reset a node')]
reset-node node *args:
    talosctl -n "{{ node }}" reset --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --system-labels-to-wipe u-local-hostpath --graceful=false {{ args }}

[confirm('Shutdown node ' + node + ' [y|N] ?')]
[doc('Shutdown a node')]
shutdown-node node *args:
    talosctl -n "{{ node }}" shutdown --force {{ args }}

[confirm('Upgrade Kubernetes to ' + version + ' [y|N] ?')]
[doc('Upgrade Kubernetes version on the cluster')]
upgrade-k8s version:
    talosctl -n "$(talosctl config info -o yaml | yq -e '.endpoints[0]')" upgrade-k8s --to {{ version }}

[confirm('Upgrade node ' + node + ' [y|N] ?')]
[doc('Upgrade Talos version on a node')]
upgrade-node node *args:
    talosctl -n "{{ node }}" upgrade -i "$(just talos machine-image "{{ node }}")" -m powercycle --timeout=10m {{ args }}

[private]
machine-image node:
    just talos render-config "{{ node }}" | yq -e 'select(.machine.install) | .machine.install.image'

[private]
node-role node:
    role="controlplane"
    if [[ -f "{{ source_directory() }}/nodes/workers/{{ node }}.yaml.j2" ]]; then
        role="workers"
    fi
    echo "$role"

[private]
schematic-file node:
    file="{{ source_directory() }}/schematic.yaml.j2"
    for f in "{{ source_directory() }}"/nodes/*/"{{ node }}".schematic.yaml.j2; do
        [[ -f "$f" ]] && file="$f"
    done
    echo "$file"

[private]
schematic-id node iso="false":
    node_file="{{ source_directory() }}/nodes/$(just talos node-role "{{ node }}")/{{ node }}.yaml.j2"
    node_ip="$(grep -m1 '^# talos:node-ip=' "${node_file}" | cut -d= -f2 || true)"
    curl -sX POST --data-binary @<(just template "$(just talos schematic-file "{{ node }}")" -D "iso={{ iso }}" -D "node_ip=${node_ip}") "https://factory.talos.dev/schematics" | jq -r '.id'
